"""Severity + escalation assessment for incoming incidents.

Three assessors share one output shape (severity, escalate, reason):

* ``rules``     - the original keyword rules from the investigation agent (no API calls).
* ``llm``       - Gemini reads the Sentry event only.
* ``llm_repo``  - Gemini reads the Sentry event plus source files from the GitHub repo
                  (the files named in the stack trace, plus the repo README).

The LLM assessors fall back to ``rules`` if the model call fails or returns bad JSON,
and record that in ``assessor`` so a fallback is never mistaken for a model answer.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from app.agents.models import IncidentMessage, RepositoryContext
from app.config import settings

SEVERITIES = ("high", "medium", "low")


@dataclass
class Assessment:
    severity: str
    escalate: bool
    reason: str
    assessor: str
    model: str | None = None
    context_files: list[str] | None = None
    duration_ms: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- rules


def incident_text(msg: IncidentMessage) -> str:
    return " ".join(
        str(part)
        for part in [
            msg.title,
            msg.full_error,
            msg.http_method,
            msg.route,
            msg.status_code,
            msg.event_type,
        ]
        if part is not None
    ).lower()


def rule_severity(msg: IncidentMessage) -> str:
    """Original investigation-agent rule, unchanged so it can serve as the baseline."""
    text = incident_text(msg)

    if (
        msg.level == "fatal"
        or (msg.status_code is not None and msg.status_code >= 500)
        or "critical" in text
    ):
        return "high"

    if msg.level == "error" or "exception" in text:
        return "medium"

    return "low"


def assess_rules(msg: IncidentMessage) -> Assessment:
    severity = rule_severity(msg)
    # The original code had no escalation step; the baseline escalates exactly the
    # incidents its rule calls "high".
    return Assessment(
        severity=severity,
        escalate=severity == "high",
        reason=f"Keyword rule: level={msg.level}, status_code={msg.status_code}.",
        assessor="rules",
    )


# --------------------------------------------------------------------------- LLM

SYSTEM_PROMPT = """You are the on-call triage assistant for a production web service.
Given one Sentry alert (and sometimes the source code it points to), decide:

severity:
  high   - a core user flow (checkout, payment, login/auth, account data) is failing or
           at real risk for many users, or there is data loss/corruption or a security
           exposure.
  medium - a real defect with limited impact: a non-core feature, a minority of users,
           a degraded path that still has a working fallback, or a background job that
           needs fixing soon but is not hurting users right now.
  low    - cosmetic issues, log-message problems, expected client errors, scanner/bot
           noise, or anything in a non-production environment with no user impact.

escalate:
  true   - page the on-call engineer now: waiting until business hours would cause
           significant user, revenue, data, or security harm.
  false  - it can wait for the normal ticket queue.

Judge from the evidence you are given. Take into account the alert's time and tags
and the recent incidents: an alert can describe something that has already recovered,
that duplicates an incident someone is already working, or that is expected during
planned work. When source code is provided, use it to check what the failing code
actually does: whether errors are caught or retried, whether the path is behind a
disabled flag or deprecated, and what the failure affects.

Reply with JSON only: {"severity": "high|medium|low", "escalate": true|false,
"reason": "<one sentence>"}"""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "severity": {"type": "string", "enum": list(SEVERITIES)},
        "escalate": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["severity", "escalate", "reason"],
}


def build_user_prompt(msg: IncidentMessage, repo_context: RepositoryContext | None) -> str:
    frames = "\n".join(f"  {frame}" for frame in msg.stack_frames) or "  (no stack frames)"
    recent = "\n".join(
        f"  - {incident.title} [severity={incident.severity}, status={incident.status}]"
        + (f" note: {incident.recommendation}" if incident.recommendation else "")
        for incident in msg.recent_incidents
    ) or "  (none)"
    tags = ", ".join(f"{key}={value}" for key, value in msg.tags.items()) or "(none)"

    parts = [
        "SENTRY ALERT",
        f"title: {msg.title}",
        f"level: {msg.level}",
        f"environment: {msg.environment or 'unknown'}",
        f"event time: {msg.event_time or 'unknown'}",
        f"tags: {tags}",
        f"culprit: {msg.culprit or 'unknown'}",
        f"request: {msg.http_method or '-'} {msg.route or '-'} status={msg.status_code}",
        f"details:\n{msg.full_error or '(none)'}",
        f"stack (oldest call first):\n{frames}",
        f"recent incidents:\n{recent}",
    ]

    if repo_context is not None:
        files = "\n\n".join(
            f"FILE: {file.path}{' (truncated)' if file.truncated else ''}\n{file.content}"
            for file in repo_context.files
        ) or "(no files could be loaded)"
        parts.append(f"REPOSITORY CONTEXT ({repo_context.repo_full_name}@{repo_context.default_branch})\n{files}")

    return "\n\n".join(parts)


class BudgetExceeded(RuntimeError):
    pass


def _reserve_call() -> None:
    """Append one line per Gemini attempt to a shared ledger and refuse past the cap.

    The ledger is a file so the separate agent processes and the eval scripts all
    count against the same budget.
    """
    ledger = os.environ.get("GEMINI_CALL_LEDGER")
    cap = os.environ.get("GEMINI_CALL_BUDGET")

    if not ledger:
        return

    path = Path(ledger)
    path.parent.mkdir(parents=True, exist_ok=True)
    used = len(path.read_text(encoding="utf-8").splitlines()) if path.exists() else 0

    if cap is not None and used >= int(cap):
        raise BudgetExceeded(f"Gemini call budget of {cap} reached ({used} used)")

    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{time.time():.3f} {os.environ.get('GEMINI_CALL_TAG', '-')}\n")


def call_gemini(system_prompt: str, user_prompt: str) -> dict:
    from google import genai
    from google.genai import types

    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    from google.genai import errors

    client = genai.Client(api_key=settings.gemini_api_key)
    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=0,
        response_mime_type="application/json",
        response_schema=RESPONSE_SCHEMA,
    )

    # Retry rate limits and transient server errors; every attempt counts against the budget.
    for delay in [10, 30, None]:
        _reserve_call()
        try:
            response = client.models.generate_content(
                model=settings.gemini_model, contents=user_prompt, config=config
            )
            break
        except errors.APIError as exc:
            if delay is None or exc.code not in {429, 500, 503}:
                raise
            time.sleep(delay)

    data = json.loads(response.text or "")

    severity = str(data.get("severity", "")).lower()
    if severity not in SEVERITIES or not isinstance(data.get("escalate"), bool):
        raise ValueError(f"Model returned an invalid assessment: {data!r}")

    return {"severity": severity, "escalate": data["escalate"], "reason": str(data.get("reason", "")).strip()}


def assess_llm(msg: IncidentMessage, repo_context: RepositoryContext | None = None) -> Assessment:
    assessor = "llm_repo" if repo_context is not None else "llm"
    started = time.perf_counter()

    try:
        result = call_gemini(SYSTEM_PROMPT, build_user_prompt(msg, repo_context))
    except BudgetExceeded:
        raise
    except Exception as exc:  # network, quota, malformed JSON
        fallback = assess_rules(msg)
        fallback.assessor = f"{assessor}_fallback_rules"
        fallback.reason = f"LLM unavailable ({type(exc).__name__}: {exc}); {fallback.reason}"
        return fallback

    return Assessment(
        severity=result["severity"],
        escalate=result["escalate"],
        reason=result["reason"],
        assessor=assessor,
        model=settings.gemini_model,
        context_files=[file.path for file in repo_context.files] if repo_context else None,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


# --------------------------------------------------------------------------- entry point


def load_assessment_context(msg: IncidentMessage) -> RepositoryContext:
    from app.services.github_service import load_repository_context

    return load_repository_context(
        repo_full_name=msg.repo_full_name,
        default_branch=msg.default_branch,
        files_to_inspect=[*msg.stack_files, "README.md"],
        include_defaults=False,
    )


def assess(msg: IncidentMessage, mode: str | None = None) -> Assessment:
    mode = (mode or settings.severity_assessor).strip().lower()

    if mode == "rules":
        return assess_rules(msg)

    if mode == "llm":
        return assess_llm(msg)

    if mode == "llm_repo":
        return assess_llm(msg, load_assessment_context(msg))

    raise ValueError(f"Unknown SEVERITY_ASSESSOR mode: {mode!r}")
