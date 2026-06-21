from app.agents.models import IncidentMessage


def build_incident_recommendation(message: IncidentMessage) -> str:
    """Create a safe, actionable recommendation without calling an external LLM."""
    location = message.culprit or message.transaction or "the affected request handler"
    request = " ".join(
        value for value in (message.request_method, message.request_path) if value
    ) or "the affected request"
    status_code = message.status_code

    if status_code in {401, 403}:
        return (
            f"The system needs to classify the {status_code} from {request} as either "
            "expected access control or an authentication regression. "
            f"Inspect the authentication dependency or middleware used by {location}, "
            "and verify that valid credentials reach the handler. Add tests for both "
            "authenticated and unauthenticated requests. If this response is expected, "
            "stop reporting it as a Sentry warning by filtering this event type or "
            "lowering it to informational telemetry. Do not weaken authentication or "
            "change the endpoint to return success for unauthenticated callers."
        )

    if status_code == 404:
        return (
            f"The system needs to verify routing for {request}. Confirm that the client "
            f"uses the intended path and that {location} is registered under the expected "
            "router prefix. Add a route-level regression test. If the 404 is expected, "
            "filter it from Sentry rather than changing route behavior."
        )

    if status_code == 429:
        return (
            f"The system needs to review rate limiting and capacity for {request}. "
            "Confirm whether the limit is intentional, return retry guidance to clients, "
            "and add monitoring for sustained throttling before changing the configured limit."
        )

    if status_code is not None and status_code >= 500:
        return (
            f"The system needs a minimal fix in {location} for the {status_code} response "
            f"from {request}. Reproduce the failing request, inspect the innermost in-app "
            "stack frame, guard the failing dependency or input boundary, and add a "
            "regression test before deployment."
        )

    if message.error_type:
        return (
            f"The system needs to reproduce {message.error_type} in {location}, inspect "
            "the innermost in-app stack frame, correct the smallest failing boundary, and "
            "add a regression test covering the reported input and environment."
        )

    return (
        f"The system needs to reproduce the event in {location}, confirm whether it is "
        "actionable or expected telemetry, inspect the affected request and available "
        "in-app frames, and add a focused regression test before making a code change."
    )


def build_final_recommendation(
    suspected_root_cause: str,
    recommendation: str,
    files_to_inspect: list[str],
) -> str:
    files = ", ".join(files_to_inspect) if files_to_inspect else "No file identified"
    return (
        "Observed finding:\n"
        f"{suspected_root_cause}\n\n"
        "What the system needs:\n"
        f"{recommendation}\n\n"
        "Suggested files to inspect:\n"
        f"{files}"
    )
