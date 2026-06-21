import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlmodel import Session
from uagents.communication import send_message
from uagents_core.types import DeliveryStatus, MsgStatus

from app.config import settings
from app.database import get_session
from app.models.incident import Incident
from app.agents.models import IncidentMessage
from app.agents.addresses import LOCAL_AGENT_RESOLVER
from app.services.sentry_event_parser import parse_sentry_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sentry", tags=["sentry"])


@router.post("/webhook")
async def sentry_webhook(
    request: Request,
    session: Session = Depends(get_session),
    sentry_hook_resource: str | None = Header(default=None, alias="Sentry-Hook-Resource"),
    sentry_hook_signature: str | None = Header(default=None, alias="Sentry-Hook-Signature"),
):
    body = await request.body()

    if settings.sentry_webhook_secret:
        if not sentry_hook_signature:
            raise HTTPException(status_code=401, detail="Missing Sentry webhook signature")

        digest = hmac.new(
            settings.sentry_webhook_secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(digest, sentry_hook_signature):
            raise HTTPException(status_code=401, detail="Invalid Sentry webhook signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    try:
        parsed = parse_sentry_event(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    breakdown = parsed.summary()
    recommendation_parts = []
    if parsed.triggered_rule:
        recommendation_parts.append(
            f"Sentry alert received from rule: {parsed.triggered_rule}"
        )
    if breakdown:
        recommendation_parts.append(f"Event breakdown: {breakdown}")

    incident = Incident(
        sentry_issue_id=parsed.issue_id,
        title=parsed.title,
        issue_url=parsed.permalink,
        repo_full_name=settings.default_repo_full_name,
        status="received",
        severity=parsed.level or "unknown",
        recommendation="\n".join(recommendation_parts) or None,
    )
    
    session.add(incident)
    session.commit()
    session.refresh(incident)

    if incident.id is None:
        raise HTTPException(status_code=500, detail="Incident was created without an id")

    repo_full_name = incident.repo_full_name
    if not repo_full_name and parsed.sentry_project and "/" in parsed.sentry_project:
        repo_full_name = parsed.sentry_project

    if not repo_full_name:
        raise HTTPException(
            status_code=500,
            detail="Missing repo_full_name. Set DEFAULT_REPO_FULL_NAME in .env",
        )

    if not settings.investigation_agent_address:
        raise HTTPException(
            status_code=500,
            detail="Missing INVESTIGATION_AGENT_ADDRESS in .env",
        )

    msg = IncidentMessage(
        incident_id=incident.id,
        sentry_issue_id=incident.sentry_issue_id,
        title=incident.title,
        culprit=parsed.culprit,
        permalink=incident.issue_url,
        repo_full_name=repo_full_name,
        default_branch=settings.default_branch,
        event_id=parsed.event_id,
        level=parsed.level,
        environment=parsed.environment,
        platform=parsed.platform,
        release=parsed.release,
        transaction=parsed.transaction,
        error_type=parsed.error_type,
        error_value=parsed.error_value,
        request_method=parsed.request_method,
        request_url=parsed.request_url,
        request_path=parsed.request_path,
        status_code=parsed.status_code,
        tags=parsed.tags,
        stacktrace_frames=parsed.stacktrace_frames,
    )

    try:
        logger.info(
            "Send started sender=fastapi_sentry_webhook recipient=%s "
            "message_type=%s incident_id=%s",
            settings.investigation_agent_address,
            type(msg).__name__,
            msg.incident_id,
        )
        status = await send_message(
            destination=settings.investigation_agent_address,
            message=msg,
            resolver=LOCAL_AGENT_RESOLVER,
            timeout=30,
        )
        if isinstance(status, MsgStatus) and status.status != DeliveryStatus.DELIVERED:
            raise RuntimeError(
                f"Agent message delivery failed: {status.status} ({status.detail})"
            )
        logger.info(
            "Send finished sender=fastapi_sentry_webhook recipient=%s "
            "message_type=%s incident_id=%s result=%s",
            settings.investigation_agent_address,
            type(msg).__name__,
            msg.incident_id,
            status,
        )

        incident.status = "agent_workflow_started"
        session.add(incident)
        session.commit()
        session.refresh(incident)

    except Exception as exc:
        incident.status = "agent_workflow_failed_to_start"
        incident.recommendation = (
            f"{incident.recommendation or ''}\n"
            f"Failed to start Fetch.ai workflow: {str(exc)}"
        ).strip()

        session.add(incident)
        session.commit()
        session.refresh(incident)

        raise HTTPException(
            status_code=502,
            detail=f"Incident saved, but failed to start Fetch.ai workflow: {str(exc)}",
        )

    return {
        "received": True,
        "incident_id": incident.id,
        "status": incident.status,
        "resource": sentry_hook_resource,
        "sentry_issue_id": incident.sentry_issue_id,
        "title": incident.title,
        "breakdown": {
            "event_id": parsed.event_id,
            "level": parsed.level,
            "environment": parsed.environment,
            "platform": parsed.platform,
            "release": parsed.release,
            "culprit": parsed.culprit,
            "error_type": parsed.error_type,
            "error_value": parsed.error_value,
            "request_method": parsed.request_method,
            "request_path": parsed.request_path,
            "status_code": parsed.status_code,
            "stacktrace_frame_count": len(parsed.stacktrace_frames),
        },
    }
