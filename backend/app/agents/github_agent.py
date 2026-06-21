from uagents import Agent, Context

from app.agents.models import InvestigationResult, PatchRequest
from app.agents.addresses import (
    GITHUB_AGENT_ENDPOINT,
    GITHUB_SEED,
    LOCAL_AGENT_RESOLVER,
    PATCH_AGENT_ADDRESS,
)
from app.agents.messaging import send_with_debug

github_agent = Agent(
    name="github_agent",
    seed=GITHUB_SEED,
    port=8004,
    endpoint=[GITHUB_AGENT_ENDPOINT],
    resolve=LOCAL_AGENT_RESOLVER,
)


@github_agent.on_message(model=InvestigationResult)
async def fetch_repo_context(ctx: Context, sender: str, msg: InvestigationResult):
    ctx.logger.info(f"Fetching GitHub context for incident {msg.incident_id}")

    patch_request = PatchRequest(
        incident_id=msg.incident_id,
        repo_full_name=msg.repo_full_name,
        default_branch="main",
        suspected_root_cause=msg.suspected_root_cause,
        recommendation=msg.recommendation,
        files_to_inspect=msg.files_to_inspect,
    )

    ctx.logger.info(f"Forwarding patch request to Patch agent for incident {msg.incident_id}")

    await send_with_debug(
        ctx,
        sender_name="github_agent",
        recipient=PATCH_AGENT_ADDRESS,
        message=patch_request,
    )


if __name__ == "__main__":
    print("GitHub address:", github_agent.address)
    github_agent.run()
