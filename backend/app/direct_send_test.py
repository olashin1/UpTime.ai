import asyncio

from uagents.communication import send_message
from uagents_core.types import DeliveryStatus, MsgStatus

from app.agents.addresses import GITHUB_AGENT_ADDRESS, LOCAL_AGENT_RESOLVER
from app.agents.models import InvestigationResult


async def main() -> None:
    message = InvestigationResult(
        incident_id=9001,
        sentry_issue_id="direct-send-test",
        repo_full_name="local/direct-send-test",
        severity="medium",
        suspected_root_cause="Direct local delivery test",
        files_to_inspect=[],
        recommendation="Verify GitHub, Patch, and Validation handlers run.",
    )

    print(
        "Send started sender=direct_send_test "
        f"recipient={GITHUB_AGENT_ADDRESS} message_type=InvestigationResult "
        f"incident_id={message.incident_id}"
    )
    result = await send_message(
        destination=GITHUB_AGENT_ADDRESS,
        message=message,
        resolver=LOCAL_AGENT_RESOLVER,
        timeout=10,
    )
    print(
        "Send finished sender=direct_send_test "
        f"recipient={GITHUB_AGENT_ADDRESS} message_type=InvestigationResult "
        f"incident_id={message.incident_id} result={result}"
    )

    if not isinstance(result, MsgStatus) or result.status != DeliveryStatus.DELIVERED:
        raise SystemExit("Direct send was not delivered")


if __name__ == "__main__":
    asyncio.run(main())
