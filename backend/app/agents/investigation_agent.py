from uagents import Agent, Context

from app.agents.models import IncidentMessage, InvestigationResult
from app.agents.addresses import (
    GITHUB_AGENT_ADDRESS,
    INVESTIGATION_AGENT_ENDPOINT,
    INVESTIGATION_SEED,
    LOCAL_AGENT_RESOLVER,
)
from app.agents.messaging import send_with_debug
from app.services.recommendation_service import build_incident_recommendation

investigation_agent = Agent(
    name="investigation_agent",
    seed=INVESTIGATION_SEED,
    port=8002,
    endpoint=[INVESTIGATION_AGENT_ENDPOINT],
    resolve=LOCAL_AGENT_RESOLVER,
)


@investigation_agent.on_message(model=IncidentMessage)
async def investigate(ctx: Context, sender: str, msg: IncidentMessage):
    ctx.logger.info(f"Investigating Sentry issue: {msg.sentry_issue_id}")
    ctx.logger.info(
        "Sentry breakdown incident_id=%s event_id=%s level=%s environment=%s "
        "error_type=%s request=%s %s status_code=%s culprit=%s stacktrace_frames=%s",
        msg.incident_id,
        msg.event_id,
        msg.level,
        msg.environment,
        msg.error_type,
        msg.request_method,
        msg.request_path,
        msg.status_code,
        msg.culprit,
        len(msg.stacktrace_frames),
    )

    severity = "low"
    if msg.level in {"fatal", "error"} or (msg.status_code or 0) >= 500:
        severity = "high"
    elif msg.level == "warning" or (msg.status_code or 0) >= 400:
        severity = "medium"

    cause_parts = []
    if msg.error_type or msg.error_value:
        cause_parts.append(
            ": ".join(value for value in (msg.error_type, msg.error_value) if value)
        )
    if msg.request_method or msg.request_path:
        request = " ".join(
            value for value in (msg.request_method, msg.request_path) if value
        )
        if msg.status_code is not None:
            request += f" returned {msg.status_code}"
        cause_parts.append(request)
    if msg.culprit:
        cause_parts.append(f"reported by {msg.culprit}")

    files_to_inspect = list(
        dict.fromkeys(
            frame.filename
            for frame in msg.stacktrace_frames
            if frame.filename and (frame.in_app is not False)
        )
    )

    result = InvestigationResult(
        incident_id=msg.incident_id,
        sentry_issue_id=msg.sentry_issue_id,
        repo_full_name=msg.repo_full_name,
        severity=severity,
        suspected_root_cause="; ".join(cause_parts)
        or f"Possible failure near {msg.culprit or 'unknown module'}",
        files_to_inspect=files_to_inspect,
        recommendation=build_incident_recommendation(msg),
    )

    ctx.logger.info(
        f"Forwarding investigation result to Github agent for incident {msg.incident_id}"
    )
    await send_with_debug(
        ctx,
        sender_name="investigation_agent",
        recipient=GITHUB_AGENT_ADDRESS,
        message=result,
    )


if __name__ == "__main__":
    print("Investigation address:", investigation_agent.address)
    investigation_agent.run()
