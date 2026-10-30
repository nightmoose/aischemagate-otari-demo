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
    "routing policies wilding-extractor (DeepInfra Qwen3) and wilding-repairer (OVHcloud Mistral) returned HTTP 200 on 2026-10-30 12:25 PM ET",
    "guardrail wilding-prompt-injection monitor: header otari-guardrails valid true, score 0.0",
    "guardrail wilding-prompt-injection block: sample 05 HTTP 403 code guardrail_violation, score 1.0",
    "sample 04 quarantine is model-dependent: an earlier run left ticket_id missing; the 2026-10-30 12:25 PM ET policy run passed on the first extraction",
)

# Budgets are set in the dashboard. No completion has been shown hitting them.
DASHBOARD_CONFIGURED = (
    "budget wilding-cap is $2 monthly, applied as workspace ceiling wilding-workspace-ceiling",
    "member budget wilding-member-cap is $1",
)

# Not observed on a hosted completion.
UNVERIFIED = (
    "workspace ceiling wilding-workspace-ceiling and member budget wilding-member-cap",
    "hosted workspace MCP",
    "hosted per-user budget header Otari-End-User-Budget",
)
