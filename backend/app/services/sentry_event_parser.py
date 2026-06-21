from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from app.agents.models import SentryStackFrame


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _integer(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _tags(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        return {str(key): str(item) for key, item in value.items()}

    result: dict[str, str] = {}
    if isinstance(value, list):
        for item in value:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                result[str(item[0])] = str(item[1])
    return result


@dataclass(frozen=True)
class ParsedSentryEvent:
    issue_id: str
    title: str
    event_id: str | None = None
    permalink: str | None = None
    culprit: str | None = None
    level: str | None = None
    environment: str | None = None
    platform: str | None = None
    release: str | None = None
    transaction: str | None = None
    error_type: str | None = None
    error_value: str | None = None
    request_method: str | None = None
    request_url: str | None = None
    request_path: str | None = None
    status_code: int | None = None
    sentry_project: str | None = None
    triggered_rule: str | None = None
    tags: dict[str, str] = field(default_factory=dict)
    stacktrace_frames: list[SentryStackFrame] = field(default_factory=list)

    def summary(self) -> str:
        parts = []
        if self.level:
            parts.append(f"level={self.level}")
        if self.environment:
            parts.append(f"environment={self.environment}")
        if self.error_type:
            parts.append(f"type={self.error_type}")
        if self.status_code is not None:
            parts.append(f"status_code={self.status_code}")
        if self.request_method or self.request_path:
            request = " ".join(
                value for value in (self.request_method, self.request_path) if value
            )
            parts.append(f"request={request}")
        if self.culprit:
            parts.append(f"culprit={self.culprit}")
        return ", ".join(parts)


def parse_sentry_event(payload: dict[str, Any]) -> ParsedSentryEvent:
    if not isinstance(payload, dict):
        raise ValueError("Sentry payload must be a JSON object")

    data = _mapping(payload.get("data"))
    event = _mapping(data.get("event"))
    issue = _mapping(data.get("issue"))

    issue_id = _text(event.get("issue_id")) or _text(issue.get("id"))
    if not issue_id:
        raise ValueError("Missing Sentry issue id")

    metadata = _mapping(event.get("metadata"))
    logentry = _mapping(event.get("logentry"))
    extra = _mapping(event.get("extra"))
    request = _mapping(event.get("request"))
    tags = _tags(event.get("tags"))

    exception_values = _mapping(event.get("exception")).get("values")
    exceptions = (
        [item for item in exception_values if isinstance(item, dict)]
        if isinstance(exception_values, list)
        else []
    )
    primary_exception = exceptions[-1] if exceptions else {}

    error_type = _text(primary_exception.get("type")) or _text(
        extra.get("event_type")
    )
    error_value = _text(primary_exception.get("value"))

    title = (
        _text(event.get("title"))
        or _text(issue.get("title"))
        or _text(metadata.get("title"))
        or _text(logentry.get("formatted"))
        or _text(event.get("message"))
        or error_value
        or error_type
        or "Unknown Sentry issue"
    )
    if not error_value:
        error_value = _text(event.get("message")) or title

    frames: list[SentryStackFrame] = []
    frame_sources = exceptions or [event]
    for source in frame_sources:
        raw_frames = _mapping(source.get("stacktrace")).get("frames")
        if not isinstance(raw_frames, list):
            continue
        for raw_frame in raw_frames[-20:]:
            if not isinstance(raw_frame, dict):
                continue
            raw_in_app = raw_frame.get("in_app")
            frames.append(
                SentryStackFrame(
                    filename=_text(raw_frame.get("filename"))
                    or _text(raw_frame.get("abs_path")),
                    function=_text(raw_frame.get("function")),
                    line_number=_integer(raw_frame.get("lineno")),
                    context_line=_text(raw_frame.get("context_line")),
                    in_app=raw_in_app if isinstance(raw_in_app, bool) else None,
                )
            )

    request_url = _text(request.get("url"))
    request_path = _text(extra.get("path")) or _text(extra.get("route"))
    if not request_path and request_url:
        request_path = urlparse(request_url).path or None

    contexts = _mapping(event.get("contexts"))
    response_context = _mapping(contexts.get("response"))
    status_code = (
        _integer(extra.get("status_code"))
        or _integer(tags.get("http.status_code"))
        or _integer(response_context.get("status_code"))
    )

    sentry_project_value = event.get("project") or payload.get("project")

    return ParsedSentryEvent(
        issue_id=issue_id,
        event_id=_text(event.get("event_id")),
        title=title,
        permalink=_text(event.get("web_url"))
        or _text(event.get("issue_url"))
        or _text(issue.get("permalink")),
        culprit=_text(event.get("culprit")) or _text(event.get("transaction")),
        level=_text(event.get("level")) or _text(tags.get("level")),
        environment=_text(event.get("environment"))
        or _text(tags.get("environment")),
        platform=_text(event.get("platform")),
        release=_text(event.get("release")) or _text(tags.get("release")),
        transaction=_text(event.get("transaction")),
        error_type=error_type,
        error_value=error_value,
        request_method=_text(request.get("method"))
        or _text(extra.get("method"))
        or _text(tags.get("http.method")),
        request_url=request_url,
        request_path=request_path,
        status_code=status_code,
        sentry_project=_text(sentry_project_value),
        triggered_rule=_text(data.get("triggered_rule"))
        or _text(_mapping(data.get("issue_alert")).get("title")),
        tags=tags,
        stacktrace_frames=frames,
    )
