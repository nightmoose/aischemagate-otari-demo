"""Role models, token cap, and the hosted Otari base URL."""

# Probed 2026-10-30 without a key: this URL returned HTTP 401 (route exists).
# https://api.otari.ai/v1 returned HTTP 404 and told the client to use /api/v1.
DEFAULT_BASE_URL = "https://otari.ai/api/v1"

# Open-weight extractor. Vendor: Alibaba. Plain vendor/model id.
EXTRACTOR_MODEL = "alibaba/qwen3-235b-a22b-instruct-2507"

# Open-weight repairer. Vendor: Mistral. A different vendor from the extractor.
REPAIRER_MODEL = "mistralai/mistral-small-3.2-24b-instruct-2506"

# Client-side backup used when the role model fails with a retryable error.
FALLBACK_MODEL = "openai/gpt-oss-120b"

# Hard ceiling so a flag cannot send an unbounded generation.
MAX_TOKENS_LIMIT = 512
DEFAULT_MAX_TOKENS = 256

DEFAULT_USER = "demo-operator"
DEFAULT_GUARDRAIL_PROFILE = "prompt-injection"
DEFAULT_GUARDRAIL_MODE = "monitor"

# Chat completions the process did not send are not evidence of gateway behavior.
UNVERIFIED = (
    "live Otari chat completions",
    "dashboard routing policy",
    "hosted workspace MCP",
    "hosted guardrail mandate",
    "hosted per-user budget header",
)
