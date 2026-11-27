from app.agents.models import IncidentMessage
from app.routes.sentry import _stack_from_event
from app.services import severity_service
from app.services.severity_service import assess, assess_llm


def _msg(**kwargs) -> IncidentMessage:
    base = dict(incident_id=1, sentry_issue_id="1", title="t", repo_full_name="o/r")
    base.update(kwargs)
    return IncidentMessage(**base)


def test_rules_baseline_matches_original_rule():
    assert assess(_msg(level="error", status_code=500), "rules").severity == "high"
    assert assess(_msg(level="error"), "rules").severity == "medium"
    low = assess(_msg(level="warning"), "rules")
    assert (low.severity, low.escalate) == ("low", False)


def test_stack_frames_keep_in_app_and_prefer_raise_site():
    event = {
        "exception": {
            "values": [
                {
                    "stacktrace": {
                        "frames": [
                            {"filename": "lib/site.py", "function": "x", "lineno": 1, "in_app": False},
                            {"filename": "app/routes.py", "function": "checkout", "lineno": 10, "in_app": True},
                            {"filename": "app/payments.py", "function": "charge", "lineno": 42, "in_app": True},
                        ]
                    }
                }
            ]
        }
    }
    frames, files = _stack_from_event(event)
    assert frames == ["app/routes.py:checkout:10", "app/payments.py:charge:42"]
    assert files == ["app/payments.py", "app/routes.py"]


def test_llm_failure_falls_back_to_rules_and_says_so(monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(severity_service, "call_gemini", boom)
    result = assess_llm(_msg(level="error", status_code=503))
    assert result.assessor == "llm_fallback_rules"
    assert result.severity == "high"


def test_budget_ledger_refuses_past_cap(tmp_path, monkeypatch):
    ledger = tmp_path / "calls.log"
    ledger.write_text("1 a\n2 b\n", encoding="utf-8")
    monkeypatch.setenv("GEMINI_CALL_LEDGER", str(ledger))
    monkeypatch.setenv("GEMINI_CALL_BUDGET", "2")
    try:
        severity_service._reserve_call()
    except severity_service.BudgetExceeded:
        return
    raise AssertionError("expected BudgetExceeded")


def test_prompt_includes_tags_time_and_open_incident_status():
    from app.agents.models import RecentIncident
    from app.routes.sentry import _tags_from_event

    tags = _tags_from_event({"tags": [["maintenance_window", "active"], ["level", "error"]]})
    assert tags == {"maintenance_window": "active"}

    msg = _msg(
        tags=tags,
        event_time="2026-11-27T22:10:00Z",
        recent_incidents=[
            RecentIncident(incident_id=2, sentry_issue_id="2", title="t", status="investigating",
                           severity="high", recommendation="Acknowledged by on-call")
        ],
    )
    prompt = severity_service.build_user_prompt(msg, None)
    assert "maintenance_window=active" in prompt
    assert "2026-11-27T22:10:00Z" in prompt
    assert "status=investigating" in prompt and "Acknowledged by on-call" in prompt
