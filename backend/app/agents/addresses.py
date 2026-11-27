from uagents.crypto import Identity
from uagents.resolver import RulesBasedResolver

INVESTIGATION_SEED = "investigation-agent-secret-seed"
PATCH_SEED = "patch-agent-secret-seed"
GITHUB_SEED = "github-agent-secret-seed"
VALIDATION_SEED = "validation-agent-secret-seed"

INVESTIGATION_AGENT_ADDRESS = Identity.from_seed(INVESTIGATION_SEED, 0).address
PATCH_AGENT_ADDRESS = Identity.from_seed(PATCH_SEED, 0).address
GITHUB_AGENT_ADDRESS = Identity.from_seed(GITHUB_SEED, 0).address
VALIDATION_AGENT_ADDRESS = Identity.from_seed(VALIDATION_SEED, 0).address

INVESTIGATION_AGENT_ENDPOINT = "http://127.0.0.1:8002/submit"
PATCH_AGENT_ENDPOINT = "http://127.0.0.1:8003/submit"
GITHUB_AGENT_ENDPOINT = "http://127.0.0.1:8004/submit"
VALIDATION_AGENT_ENDPOINT = "http://127.0.0.1:8005/submit"

LOCAL_AGENT_ENDPOINTS = {
    INVESTIGATION_AGENT_ADDRESS: INVESTIGATION_AGENT_ENDPOINT,
    PATCH_AGENT_ADDRESS: PATCH_AGENT_ENDPOINT,
    GITHUB_AGENT_ADDRESS: GITHUB_AGENT_ENDPOINT,
    VALIDATION_AGENT_ADDRESS: VALIDATION_AGENT_ENDPOINT,
}

LOCAL_AGENT_RESOLVER = RulesBasedResolver(LOCAL_AGENT_ENDPOINTS)
