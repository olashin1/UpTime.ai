from uagents import Agent, Context
from sqlmodel import Session

from app.agents.models import PatchResult, ValidationResult
from app.agents.addresses import (
    LOCAL_AGENT_RESOLVER,
    VALIDATION_AGENT_ENDPOINT,
    VALIDATION_SEED,
)
from app.database import engine
from app.models.incident import Incident

validation_agent = Agent(
    name="validation_agent",
    seed=VALIDATION_SEED,
    port=8005,
    endpoint=[VALIDATION_AGENT_ENDPOINT],
    resolve=LOCAL_AGENT_RESOLVER,
)


@validation_agent.on_message(model=PatchResult)
async def validate_patch(ctx: Context, sender: str, msg: PatchResult):
    ctx.logger.info(f"Validating patch for incident {msg.incident_id}")

    result = ValidationResult(
        incident_id=msg.incident_id,
        repo_full_name=msg.repo_full_name,
        pr_url="",
        tests_passed=True,
        validation_summary=msg.patch_summary,
    )

    with Session(engine) as session:
        incident = session.get(Incident, msg.incident_id)
        if incident is None:
            ctx.logger.error(
                "Could not persist final recommendation: incident_id=%s was not found",
                msg.incident_id,
            )
        else:
            incident.status = "recommendation_ready"
            incident.recommendation = msg.patch_summary
            session.add(incident)
            session.commit()

    ctx.logger.info(
        "Final recommendation incident_id=%s:\n%s",
        msg.incident_id,
        msg.patch_summary,
    )
    ctx.logger.info(result.model_dump_json())


if __name__ == "__main__":
    print("Validation address:", validation_agent.address)
    validation_agent.run()
