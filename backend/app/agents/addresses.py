from uagents.resolver import RulesBasedResolver
from uagents_core.identity import Identity

MONITORING_SEED = "monitoring-agent-secret-seed"
INVESTIGATION_SEED = "investigation-agent-secret-seed"
PATCH_SEED = "patch-agent-secret-seed"
GITHUB_SEED = "github-agent-secret-seed"
VALIDATION_SEED = "validation-agent-secret-seed"


def _address_from_seed(seed: str) -> str:
    """Derive an address without constructing and registering a placeholder Agent."""
    return Identity.from_seed(seed, 0).address


MONITORING_AGENT_ADDRESS = _address_from_seed(MONITORING_SEED)
INVESTIGATION_AGENT_ADDRESS = _address_from_seed(INVESTIGATION_SEED)
PATCH_AGENT_ADDRESS = _address_from_seed(PATCH_SEED)
GITHUB_AGENT_ADDRESS = _address_from_seed(GITHUB_SEED)
VALIDATION_AGENT_ADDRESS = _address_from_seed(VALIDATION_SEED)

INVESTIGATION_AGENT_ENDPOINT = "http://127.0.0.1:8002/submit"
PATCH_AGENT_ENDPOINT = "http://127.0.0.1:8003/submit"
GITHUB_AGENT_ENDPOINT = "http://127.0.0.1:8004/submit"
VALIDATION_AGENT_ENDPOINT = "http://127.0.0.1:8005/submit"

# Local MVP routing must not depend on Almanac registration or mailbox delivery.
LOCAL_AGENT_ENDPOINTS = {
    INVESTIGATION_AGENT_ADDRESS: INVESTIGATION_AGENT_ENDPOINT,
    PATCH_AGENT_ADDRESS: PATCH_AGENT_ENDPOINT,
    GITHUB_AGENT_ADDRESS: GITHUB_AGENT_ENDPOINT,
    VALIDATION_AGENT_ADDRESS: VALIDATION_AGENT_ENDPOINT,
}
LOCAL_AGENT_RESOLVER = RulesBasedResolver(LOCAL_AGENT_ENDPOINTS)
