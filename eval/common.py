"""Shared helpers for the eval scripts. Run them from the repo root with the backend venv."""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT / "eval"
RESULTS_DIR = EVAL_DIR / "results"
BACKEND_DIR = ROOT / "backend"

sys.path.insert(0, str(BACKEND_DIR))

# Every Gemini attempt from any process is appended here; past the cap, calls are refused.
LEDGER = RESULTS_DIR / "gemini_calls.log"
DEFAULT_BUDGET = 170

# Where the repo-context assessor reads the fixture from (public GitHub, no token needed).
REPO = "olashin1/UpTime.ai"
SOURCE_ROOT = "eval/fixture_repo"

# End-to-end latency sample: 20 of the 48 cases, chosen by position before any run
# (positions 0-4 of each block of 12), so every label group is represented.
E2E_SAMPLE = [f"E{n:02d}" for n in range(1, 49) if (n - 1) % 12 < 5]


def load_cases() -> list[dict]:
    return json.loads((EVAL_DIR / "eval_errors.json").read_text(encoding="utf-8"))["cases"]


def configure_budget(tag: str, budget: int = DEFAULT_BUDGET) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["GEMINI_CALL_LEDGER"] = str(LEDGER)
    os.environ["GEMINI_CALL_BUDGET"] = str(budget)
    os.environ["GEMINI_CALL_TAG"] = tag


def calls_used() -> int:
    return len(LEDGER.read_text(encoding="utf-8").splitlines()) if LEDGER.exists() else 0


def incident_message(case: dict, repo: str, ref: str):
    """Build the IncidentMessage exactly as the webhook route does."""
    from app.agents.models import IncidentMessage, RecentIncident
    from app.routes.sentry import (
        _full_error_from_event,
        _request_context_from_event,
        _stack_from_event,
        _tags_from_event,
    )

    event = case["sentry_webhook"]["data"]["event"]
    context = _request_context_from_event(event)
    frames, files = _stack_from_event(event)
    event_time = event.get("datetime") or event.get("timestamp")

    return IncidentMessage(
        incident_id=0,
        sentry_issue_id=event["issue_id"],
        title=event["title"],
        culprit=event.get("culprit"),
        permalink=event.get("web_url"),
        repo_full_name=repo,
        default_branch=ref,
        level=event.get("level") or "unknown",
        environment=event.get("environment"),
        full_error=_full_error_from_event(event),
        http_method=context["method"],
        route=context["route"],
        status_code=context["status_code"],
        event_type=context["event_type"],
        stack_frames=frames,
        stack_files=files,
        tags=_tags_from_event(event),
        event_time=str(event_time) if event_time is not None else None,
        recent_incidents=[
            RecentIncident(incident_id=0, sentry_issue_id="0", **incident)
            for incident in case.get("recent_incidents", [])
        ],
    )


def score_row(case: dict, severity: str, escalate: bool) -> dict:
    return {
        "severity_correct": severity == case["label"]["severity"],
        "escalate_correct": escalate == case["label"]["escalate"],
    }
