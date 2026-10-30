"""Role models, token cap, and the hosted Otari base URL."""

# Probed 2026-10-30 without a key: this URL returned HTTP 401 (route exists).
# https://api.otari.ai/v1 returned HTTP 404 and told the client to use /api/v1.
DEFAULT_BASE_URL = "https://otari.ai/api/v1"

# Open-weight extractor. Vendor: Alibaba. Plain vendor/model id.
EXTRACTOR_MODEL = "alibaba/qwen3-235b-a22b-instruct-2507"

# Open-weight repairer. Vendor: Mistral. A different vendor from the extractor.
REPAIRER_MODEL = "mistralai/mistral-small-3.2-24b-instruct-2506"

# Dashboard routing policies. Callers send these names as `model`.
# The chains behind them are dashboard-configured and have not been observed
# on a completion from this client.
EXTRACTOR_POLICY = "wilding-extractor"
REPAIRER_POLICY = "wilding-repairer"

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
# Dashboard name for the Lakera Guard check. Pending there; not observed on a completion.
DEFAULT_GUARDRAIL_PROFILE = "wilding-prompt-injection"
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

# Present in the dashboard. No completion in this repo has shown these taking effect.
DASHBOARD_CONFIGURED = (
    "routing policy wilding-extractor: Qwen3-235B-A22B-Instruct-2507 on DeepInfra, then gpt-oss-120b; request model is wilding-extractor",
    "routing policy wilding-repairer: Mistral-Small-3.2-24B on OVHcloud, then gpt-oss-120b; request model is wilding-repairer",
    "budget wilding-cap is $2 monthly, applied as workspace ceiling wilding-workspace-ceiling",
    "member budget wilding-member-cap is $1",
    "guardrail wilding-prompt-injection, vendor Lakera Guard, pending",
)

# Not observed on a hosted completion.
UNVERIFIED = (
    "routing policy names wilding-extractor and wilding-repairer as the request model",
    "workspace ceiling wilding-workspace-ceiling and member budget wilding-member-cap",
    "guardrail profile wilding-prompt-injection on a completion",
    "hosted workspace MCP",
    "live guardrail block or flag on the injection sample",
    "hosted per-user budget header Otari-End-User-Budget",
)
