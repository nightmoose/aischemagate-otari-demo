"""Role models, token cap, and the hosted Otari base URL."""

# Probed 2026-10-30 without a key: this URL returned HTTP 401 (route exists).
# https://api.otari.ai/v1 returned HTTP 404 and told the client to use /api/v1.
DEFAULT_BASE_URL = "https://otari.ai/api/v1"

# Open-weight extractor. Vendor: Alibaba. Plain vendor/model id.
EXTRACTOR_MODEL = "alibaba/qwen3-235b-a22b-instruct-2507"

# Open-weight repairer. Vendor: Mistral. A different vendor from the extractor.
REPAIRER_MODEL = "mistralai/mistral-small-3.2-24b-instruct-2506"

# Client-side backup used when the role model fails with a retryable error.
# gpt-oss is a reasoning model: the fallback call uses FALLBACK_MAX_TOKENS
# so the generation cap is not spent before the JSON object. 2048 is a bound,
# not a measured minimum.
FALLBACK_MODEL = "openai/gpt-oss-120b"
FALLBACK_MAX_TOKENS = 2048

# Deliberately absent from the catalog. Sample 03 names this first so the
# gateway errors and the client falls back. Not a live-verified error code.
UNAVAILABLE_MODEL = "example/not-a-deployed-model"

# Hard ceiling for the open-weight role calls. The fallback model is exempt.
MAX_TOKENS_LIMIT = 512
DEFAULT_MAX_TOKENS = 256

# Otari rejects a `user` that does not match the API key's own user, so it is omitted by default.
DEFAULT_USER = ""
DEFAULT_GUARDRAIL_PROFILE = "prompt-injection"
DEFAULT_GUARDRAIL_MODE = "monitor"

# Observed on a hosted run. A dry-run does not re-check these.
LIVE_VERIFIED = (
    "hosted chat completions",
    "extractor role alibaba/qwen3-235b-a22b-instruct-2507",
    "repairer role mistralai/mistral-small-3.2-24b-instruct-2506",
    "repair outcome (extractor, then repairer)",
    "guardrails request field accepted by the gateway",
    "user omitted unless set; a user that does not match the API key is rejected",
    "live fallback from an unknown model id (HTTP 400 invalid_model) to openai/gpt-oss-120b",
    "live quarantine when a required field is absent from the source",
)

# Not observed on that hosted run, or not exercised by an authenticated call.
UNVERIFIED = (
    "dashboard routing policy",
    "hosted workspace MCP",
    "hosted guardrail mandate",
    "live guardrail block or flag on the injection sample",
    "hosted per-user budget header Otari-End-User-Budget",
)
