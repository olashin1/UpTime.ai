from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Incident(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    sentry_issue_id: str
    title: str
    status: str = "detected"
    # Sentry's own event level (error, warning, fatal, ...), as received.
    severity: str = "unknown"

    issue_url: Optional[str] = None
    repo_full_name: Optional[str] = None
    recommendation: Optional[str] = None
    pr_url: Optional[str] = None

    # Set by the investigation agent's severity + escalation assessor.
    agent_severity: Optional[str] = None
    escalate: Optional[bool] = None
    escalation_reason: Optional[str] = None
    assessor: Optional[str] = None
    assessed_at: Optional[datetime] = None

    # When the webhook was received (UTC).
    created_at: datetime = Field(default_factory=utc_now)
