[CmdletBinding()]
param(
    [int]$ApiPort = 8010,
    [int]$StartupTimeoutSeconds = 30,
    [string]$PayloadPath,
    [switch]$KeepArtifacts
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $repoRoot "backend"
$defaultPayloadPath = Join-Path $repoRoot "samples\sentry-event-alert.txt"
$tmpRoot = Join-Path $backendRoot "tmp"
$runId = [Guid]::NewGuid().ToString("N")
$runDirectory = Join-Path $tmpRoot "agent-chain-$runId"
$apiOutput = Join-Path $runDirectory "api.out.log"
$apiError = Join-Path $runDirectory "api.err.log"

$agentProcesses = @()
$agentOutputFiles = @{}
$apiProcess = $null
$testPassed = $false
$failure = $null

$environmentOverrides = @{
    DATABASE_URL = "sqlite:///./tmp/agent-chain-$runId/test.db"
    DEFAULT_REPO_FULL_NAME = "local/agent-chain-smoke-test"
    SENTRY_WEBHOOK_SECRET = ""
    PYTHONUNBUFFERED = "1"
}
$previousEnvironment = @{}

function Test-TcpPort {
    param([int]$Port)

    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $connection = $client.ConnectAsync("127.0.0.1", $Port)
        return $connection.Wait(250) -and $client.Connected
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function Wait-TcpPort {
    param(
        [int]$Port,
        [int]$TimeoutSeconds
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        if (Test-TcpPort -Port $Port) {
            return
        }
        Start-Sleep -Milliseconds 250
    }

    throw "Timed out waiting for TCP port $Port."
}

function Wait-LogPatterns {
    param(
        [string]$Path,
        [string[]]$Patterns,
        [int]$TimeoutSeconds
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        $content = if (Test-Path -LiteralPath $Path) {
            Get-Content -LiteralPath $Path -Raw
        }
        else {
            ""
        }

        $missing = @($Patterns | Where-Object { $content -notmatch [Regex]::Escape($_) })
        if ($missing.Count -eq 0) {
            return
        }
        Start-Sleep -Milliseconds 250
    }

    throw "Timed out waiting for agent log stages: $($missing -join ', ')"
}

function Wait-FinalRecommendation {
    param(
        [int]$ApiPort,
        [int]$IncidentId,
        [int]$TimeoutSeconds
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        $incidents = Invoke-RestMethod `
            -Method Get `
            -Uri "http://127.0.0.1:$ApiPort/api/incidents/" `
            -TimeoutSec $TimeoutSeconds
        $incident = $incidents | Where-Object { $_.id -eq $IncidentId } | Select-Object -First 1
        if ($null -ne $incident -and $incident.status -eq "recommendation_ready" -and $incident.recommendation) {
            return $incident
        }
        Start-Sleep -Milliseconds 250
    }

    throw "Timed out waiting for the final recommendation for incident $IncidentId."
}

function Stop-TestProcess {
    param([System.Diagnostics.Process]$Process)

    if ($null -eq $Process) {
        return
    }

    if (-not $Process.HasExited) {
        Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
    }
}

try {
    if (-not (Test-Path -LiteralPath $backendRoot)) {
        throw "Backend directory not found: $backendRoot"
    }

    if ([string]::IsNullOrWhiteSpace($PayloadPath)) {
        $PayloadPath = $defaultPayloadPath
    }
    elseif (-not [IO.Path]::IsPathRooted($PayloadPath)) {
        $PayloadPath = Join-Path $repoRoot $PayloadPath
    }
    if (-not (Test-Path -LiteralPath $PayloadPath)) {
        throw "Sentry payload file not found: $PayloadPath"
    }

    $payloadText = Get-Content -LiteralPath $PayloadPath -Raw
    $jsonStart = $payloadText.IndexOf("{")
    if ($jsonStart -lt 0) {
        throw "Sentry payload file does not contain a JSON object."
    }

    $headerText = $payloadText.Substring(0, $jsonStart).Trim()
    $resource = "event_alert"
    if ($headerText -match "(?im)(?:Sentry|entry)-Hook-Resource\s*:\s*([^\s]+)") {
        $resource = $Matches[1]
    }
    $body = $payloadText.Substring($jsonStart).Trim()
    try {
        $payload = $body | ConvertFrom-Json
    }
    catch {
        throw "Sentry payload contains invalid JSON: $($_.Exception.Message)"
    }

    $issueId = [string]$payload.data.event.issue_id
    if ([string]::IsNullOrWhiteSpace($issueId)) {
        $issueId = [string]$payload.data.issue.id
    }
    if ([string]::IsNullOrWhiteSpace($issueId)) {
        throw "Sentry payload does not contain data.event.issue_id or data.issue.id."
    }

    Write-Host ""
    Write-Host "Autonomous On-Call Architecture Test" -ForegroundColor Cyan
    Write-Host "Sentry -> FastAPI -> Investigation -> GitHub -> Patch -> Validation"
    Write-Host "Input file: $((Resolve-Path -LiteralPath $PayloadPath).Path)"
    Write-Host "Hook resource: $resource"
    Write-Host "Sentry issue: $issueId"
    Write-Host ""

    $python = (Get-Command python -ErrorAction Stop).Source
    $ports = @(8002, 8003, 8004, 8005, $ApiPort) | Select-Object -Unique
    $occupiedPorts = @($ports | Where-Object { Test-TcpPort -Port $_ })
    if ($occupiedPorts.Count -gt 0) {
        throw "Required ports are already in use: $($occupiedPorts -join ', ')"
    }

    New-Item -ItemType Directory -Path $runDirectory -Force | Out-Null

    Push-Location $backendRoot
    try {
        $investigationAddress = (& $python -c "from app.agents.addresses import INVESTIGATION_AGENT_ADDRESS; print(INVESTIGATION_AGENT_ADDRESS)").Trim()
    }
    finally {
        Pop-Location
    }

    $environmentOverrides.INVESTIGATION_AGENT_ADDRESS = $investigationAddress
    foreach ($name in $environmentOverrides.Keys) {
        $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
        [Environment]::SetEnvironmentVariable($name, $environmentOverrides[$name], "Process")
    }

    Write-Host "Starting Investigation, GitHub, Patch, and Validation agents..."
    $agentModules = @(
        "investigation_agent",
        "github_agent",
        "patch_agent",
        "validation_agent"
    )
    foreach ($agentModule in $agentModules) {
        $agentOutput = Join-Path $runDirectory "$agentModule.out.log"
        $agentError = Join-Path $runDirectory "$agentModule.err.log"
        $agentOutputFiles[$agentModule] = $agentOutput
        $agentProcesses += Start-Process `
            -FilePath $python `
            -ArgumentList @("-u", "-m", "app.agents.$agentModule") `
            -WorkingDirectory $backendRoot `
            -WindowStyle Hidden `
            -PassThru `
            -RedirectStandardOutput $agentOutput `
            -RedirectStandardError $agentError
    }

    foreach ($port in @(8002, 8003, 8004, 8005)) {
        Wait-TcpPort -Port $port -TimeoutSeconds $StartupTimeoutSeconds
    }

    Write-Host "Starting isolated FastAPI server on port $ApiPort..."
    $apiProcess = Start-Process `
        -FilePath $python `
        -ArgumentList @("-u", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", $ApiPort) `
        -WorkingDirectory $backendRoot `
        -WindowStyle Hidden `
        -PassThru `
        -RedirectStandardOutput $apiOutput `
        -RedirectStandardError $apiError

    Wait-TcpPort -Port $ApiPort -TimeoutSeconds $StartupTimeoutSeconds

    Write-Host "Posting test Sentry webhook..."
    $timer = [Diagnostics.Stopwatch]::StartNew()
    $response = Invoke-RestMethod `
        -Method Post `
        -Uri "http://127.0.0.1:$ApiPort/api/sentry/webhook" `
        -ContentType "application/json" `
        -Headers @{ "Sentry-Hook-Resource" = $resource } `
        -Body $body `
        -TimeoutSec $StartupTimeoutSeconds
    $timer.Stop()

    if ($response.status -ne "agent_workflow_started") {
        throw "Unexpected webhook status: $($response.status)"
    }

    Write-Host "[1/5] Sentry/FastAPI: accepted incident $($response.incident_id)"
    Write-Host (
        "      Parsed: level={0}, environment={1}, type={2}, request={3} {4}, status={5}, culprit={6}" -f `
        $response.breakdown.level,
        $response.breakdown.environment,
        $response.breakdown.error_type,
        $response.breakdown.request_method,
        $response.breakdown.request_path,
        $response.breakdown.status_code,
        $response.breakdown.culprit
    )

    $expectedStages = @{
        investigation_agent = "Investigating Sentry issue: $issueId"
        github_agent = "Fetching GitHub context for incident"
        patch_agent = "Creating patch plan for incident"
        validation_agent = "Validating patch for incident"
    }
    foreach ($agentModule in $expectedStages.Keys) {
        Wait-LogPatterns `
            -Path $agentOutputFiles[$agentModule] `
            -Patterns @($expectedStages[$agentModule]) `
            -TimeoutSeconds $StartupTimeoutSeconds
    }

    Write-Host "[2/5] Investigation: classified the incident and produced a root-cause hypothesis"
    Write-Host "[3/5] GitHub: attached repository context and forwarded a patch request"
    Write-Host "[4/5] Patch: produced a safe recommendation plan (no real code/API mutation)"

    $completedIncident = Wait-FinalRecommendation `
        -ApiPort $ApiPort `
        -IncidentId $response.incident_id `
        -TimeoutSeconds $StartupTimeoutSeconds
    Write-Host "[5/5] Validation: persisted status '$($completedIncident.status)'"

    Write-Host ""
    Write-Host "PASS: Sentry -> Investigation -> GitHub -> Patch -> Validation" -ForegroundColor Green
    Write-Host "Webhook status: $($response.status)"
    Write-Host "Elapsed: $($timer.ElapsedMilliseconds) ms"
    Write-Host ""
    Write-Host "Final recommendation:" -ForegroundColor Cyan
    Write-Host $completedIncident.recommendation
    $testPassed = $true
}
catch {
    $failure = $_
}
finally {
    Stop-TestProcess -Process $apiProcess
    foreach ($agentProcess in $agentProcesses) {
        Stop-TestProcess -Process $agentProcess
    }

    foreach ($name in $environmentOverrides.Keys) {
        [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], "Process")
    }

    if ($testPassed -and -not $KeepArtifacts -and (Test-Path -LiteralPath $runDirectory)) {
        $resolvedTmpRoot = [IO.Path]::GetFullPath($tmpRoot)
        $resolvedRunDirectory = [IO.Path]::GetFullPath($runDirectory)
        if ($resolvedRunDirectory.StartsWith($resolvedTmpRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $resolvedRunDirectory -Recurse -Force
        }
    }
}

if ($null -ne $failure) {
    Write-Host ""
    Write-Host "FAIL: Agent chain smoke test" -ForegroundColor Red
    Write-Host $failure.Exception.Message
    if (Test-Path -LiteralPath $runDirectory) {
        Write-Host "Logs preserved at: $runDirectory"
    }
    else {
        Write-Host "No test artifacts were created."
    }
    throw $failure
}

if ($KeepArtifacts) {
    Write-Host "Logs preserved at: $runDirectory"
}
