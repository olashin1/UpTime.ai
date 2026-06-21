from uagents import Agent, Context

from app.agents.models import PatchRequest, PatchResult
from app.agents.addresses import (
    LOCAL_AGENT_RESOLVER,
    PATCH_AGENT_ENDPOINT,
    PATCH_SEED,
    VALIDATION_AGENT_ADDRESS,
)
from app.agents.messaging import send_with_debug
from app.services.recommendation_service import build_final_recommendation

patch_agent = Agent(
    name="patch_agent",
    seed=PATCH_SEED,
    port=8003,
    endpoint=[PATCH_AGENT_ENDPOINT],
    resolve=LOCAL_AGENT_RESOLVER,
)


@patch_agent.on_message(model=PatchRequest)
async def create_patch(ctx: Context, sender: str, msg: PatchRequest):
    ctx.logger.info(f"Creating patch plan for incident {msg.incident_id}")

    patch_summary = build_final_recommendation(
        suspected_root_cause=msg.suspected_root_cause,
        recommendation=msg.recommendation,
        files_to_inspect=msg.files_to_inspect,
    )

    result = PatchResult(
        incident_id=msg.incident_id,
        repo_full_name=msg.repo_full_name,
        branch_name=f"fix/sentry-{msg.incident_id}",
        commit_message=f"Fix Sentry incident {msg.incident_id}",
        changed_files=msg.files_to_inspect or ["UNKNOWN_FILE"],
        patch_summary=patch_summary,
    )

    ctx.logger.info(
        f"Forwarding patch result to Validation agent for incident {msg.incident_id}"
    )

    await send_with_debug(
        ctx,
        sender_name="patch_agent",
        recipient=VALIDATION_AGENT_ADDRESS,
        message=result,
    )


if __name__ == "__main__":
    print("Patch address:", patch_agent.address)
    patch_agent.run()
