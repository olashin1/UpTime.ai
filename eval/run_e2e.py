"""End-to-end latency run: signed Sentry webhook -> agents -> assessment visible on the dashboard.

Starts the backend (port 8010), the four agents, and the Vite dashboard (port 5173) against
a fresh SQLite database, then for each case in E2E_SAMPLE:

  1. deletes existing incidents, so every case sees the same (empty) recent-incident
     history as the offline run and the outputs are comparable;
  2. records t0 and POSTs the signed webhook;
  3. waits in a real Chromium page (Playwright) until that incident's row shows its
     assessment, and records t1.

Latency = t1 - t0, measured by the client. The dashboard polls every 4 s, so this includes
polling delay; the server-side part (created_at -> assessed_at) is reported separately.

    backend/.venv/Scripts/python eval/run_e2e.py --ref <commit-sha>
"""

import argparse
import hashlib
import hmac
import json
import os
import random
import re
import secrets
import socket
import subprocess
import sys
import time
from datetime import datetime

import httpx
from playwright.sync_api import sync_playwright

from common import (
    BACKEND_DIR, E2E_SAMPLE, LEDGER, REPO, RESULTS_DIR, ROOT, SOURCE_ROOT,
    calls_used, configure_budget, load_cases, score_row,
)

API = "http://127.0.0.1:8010"
DASHBOARD = "http://127.0.0.1:5173"
TRACE = BACKEND_DIR / "workflow_trace.log"
POLL_SECONDS = 4.0  # frontend/src/App.tsx polls /api/incidents every 4000 ms


def wait_port(port: int, timeout: float = 60) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.5)
    raise TimeoutError(f"port {port} did not open")


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00").split("+")[0])


def assessor_ms(incident_id: int) -> int | None:
    if not TRACE.exists():
        return None
    pattern = re.compile(rf"\| incident={incident_id} \| severity \+ escalation assessed .*duration_ms=(\d+)")
    for line in reversed(TRACE.read_text(encoding="utf-8").splitlines()):
        match = pattern.search(line)
        if match:
            return int(match.group(1))
    return None


PIPELINE_DONE = ("stored recommendation for frontend", "recommendation not stored", "decision: stop pipeline")


def wait_pipeline_done(incident_id: int, offset: int, timeout: float = 180) -> None:
    """Wait until the agents finish this incident, so no late write lands on a reused id."""
    deadline = time.time() + timeout
    marker = f"| incident={incident_id} | "
    while time.time() < deadline:
        if TRACE.exists():
            with TRACE.open("rb") as handle:
                handle.seek(offset)
                text = handle.read().decode("utf-8", errors="replace")
            if any(marker in line and done in line for line in text.splitlines() for done in PIPELINE_DONE):
                return
        time.sleep(0.5)
    raise TimeoutError(f"agent pipeline did not finish for incident {incident_id}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ref", required=True, help="commit sha the fixture is read from")
    parser.add_argument("--budget", type=int, default=170)
    parser.add_argument("--screenshot", default=str(ROOT / "docs" / "dashboard.png"))
    parser.add_argument("--assessor", default="llm_repo", help="use 'rules' for a free plumbing check")
    parser.add_argument("--cases", nargs="*", help="run only these case ids (output: e2e_subset.json)")
    args = parser.parse_args()

    configure_budget("e2e", args.budget)
    db_path = RESULTS_DIR / "e2e.db"
    db_path.unlink(missing_ok=True)
    secret = secrets.token_hex(16)

    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{db_path.as_posix()}",
        "DEFAULT_REPO_FULL_NAME": REPO,
        "DEFAULT_BRANCH": args.ref,
        "REPO_SOURCE_ROOT": SOURCE_ROOT,
        "SEVERITY_ASSESSOR": args.assessor,
        "SENTRY_WEBHOOK_SECRET": secret,
        "GITHUB_TOKEN": "",
        "ASI_ONE_API_KEY": "",
        "PYTHONUNBUFFERED": "1",
    }
    logs = open(RESULTS_DIR / "e2e_processes.log", "w", encoding="utf-8")
    npm = "npm.cmd" if os.name == "nt" else "npm"
    procs = [
        subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8010"],
                         cwd=BACKEND_DIR, env=env, stdout=logs, stderr=subprocess.STDOUT),
        subprocess.Popen([sys.executable, "-m", "app.run_agents"],
                         cwd=BACKEND_DIR, env=env, stdout=logs, stderr=subprocess.STDOUT),
        subprocess.Popen([npm, "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173", "--strictPort"],
                         cwd=ROOT / "frontend", env=env, stdout=logs, stderr=subprocess.STDOUT),
    ]

    cases = {case["id"]: case for case in load_cases()}
    sample = [cases[case_id] for case_id in (args.cases or E2E_SAMPLE)]
    assert not any(case.get("recent_incidents") for case in sample), "sample must not need seeded history"
    rows = []
    before = calls_used()
    jitter = random.Random(20261127)

    try:
        for port in [8010, 8002, 8003, 8004, 8005, 5173]:
            wait_port(port)
        time.sleep(3)

        with sync_playwright() as pw, httpx.Client(base_url=API, timeout=60) as client:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1680, "height": 1000})
            page.goto(DASHBOARD)

            for index, case in enumerate(sample):
                # SQLite reuses ids after deletes, so wait until the dashboard has dropped the
                # previous case's row before posting the next webhook.
                for incident in client.get("/api/incidents/").json():
                    client.delete(f"/api/incidents/{incident['id']}")
                page.wait_for_function("() => !document.querySelector('[data-incident-id]')", timeout=30_000)
                trace_offset = TRACE.stat().st_size if TRACE.exists() else 0
                # Real alerts arrive at random points in the dashboard's 4 s poll cycle. Without
                # this, every webhook would land just after a poll and always wait the full 4 s.
                arrival_offset = jitter.uniform(0, POLL_SECONDS)
                time.sleep(arrival_offset)

                body = json.dumps(case["sentry_webhook"]).encode()
                signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

                t0 = time.time()
                response = client.post(
                    "/api/sentry/webhook", content=body,
                    headers={"Content-Type": "application/json", "Sentry-Hook-Resource": "event_alert",
                             "Sentry-Hook-Signature": signature},
                )
                response.raise_for_status()
                incident_id = response.json()["incident_id"]
                page.wait_for_selector(
                    f'[data-incident-id="{incident_id}"][data-assessed="true"]', timeout=120_000
                )
                t1 = time.time()

                incident = next(i for i in client.get("/api/incidents/").json() if i["id"] == incident_id)
                server_ms = int((parse_utc(incident["assessed_at"]) - parse_utc(incident["created_at"])).total_seconds() * 1000)
                rows.append({
                    "id": case["id"],
                    "incident_id": incident_id,
                    "label": case["label"],
                    "predicted": {"severity": incident["agent_severity"], "escalate": incident["escalate"]},
                    **score_row(case, incident["agent_severity"], incident["escalate"]),
                    "assessor": incident["assessor"],
                    "reason": incident["escalation_reason"],
                    "dashboard_latency_ms": int((t1 - t0) * 1000),
                    "arrival_offset_ms": int(arrival_offset * 1000),
                    "server_latency_ms": server_ms,
                    "assessor_ms": assessor_ms(incident_id),
                })
                print(f"{case['id']} dashboard={rows[-1]['dashboard_latency_ms']}ms server={server_ms}ms "
                      f"got={rows[-1]['predicted']} [{incident['assessor']}]", flush=True)

                wait_pipeline_done(incident_id, trace_offset)

                if index == 0 and args.assessor == "llm_repo":
                    # Screenshot the first case once its patch recommendation has also landed.
                    page.wait_for_selector("text=/1 queued/", timeout=120_000)
                    # The dashboard auto-expands the newest event; only click if it is collapsed.
                    open_button = page.locator(f'[data-incident-id="{incident_id}"] button', has_text="Open")
                    if open_button.count():
                        open_button.first.click()
                    page.wait_for_timeout(500)
                    os.makedirs(os.path.dirname(args.screenshot), exist_ok=True)
                    page.screenshot(path=args.screenshot, full_page=True)

            browser.close()
    finally:
        for proc in procs:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
            else:
                proc.terminate()
        logs.close()

    out = {"mode": f"e2e_{args.assessor}", "ref": args.ref, "repo": REPO, "source_root": SOURCE_ROOT,
           "sample": args.cases or E2E_SAMPLE, "gemini_calls": calls_used() - before,
           "fallbacks": sum(str(r["assessor"]).endswith("fallback_rules") for r in rows), "rows": rows}
    name = "e2e.json" if args.assessor == "llm_repo" else f"e2e_{args.assessor}.json"
    if args.cases:
        name = "e2e_subset.json"
    (RESULTS_DIR / name).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"e2e: {len(rows)} cases, gemini calls {out['gemini_calls']}, ledger {LEDGER}")


if __name__ == "__main__":
    main()
