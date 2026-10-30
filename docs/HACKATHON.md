# Hackathon notes

Demo name: Developers Wilding. Gateway: hosted Otari. Validator: AISchemaGate (`pip install aischemagate`, class `LLMGate`).

Hosted runs verified chat completions, both open-weight roles, a repair, a fallback from an unknown model id to `openai/gpt-oss-120b`, and rejection of a mismatched `user`. A later policy run on 2026-10-30 at 12:25 PM ET verified `wilding-extractor` (DeepInfra Qwen3) and `wilding-repairer` (OVHcloud Mistral) at HTTP 200, plus guardrail `wilding-prompt-injection` in monitor and block. Sample 04 passed on the first extraction in that run, so a quarantine when `ticket_id` is missing is model-dependent, not guaranteed. Items still unverified are the spend caps, hosted MCP, and the end-user budget header.

Live finding (2026-10-30, three probes): with guardrail mode `block`, the gateway answered HTTP 502 with detail "guardrail profile 'prompt-injection' requested but no guardrails service is configured. Set OTARI_GUARDRAILS_URL on the gateway or pass `url` on the guardrail entry." That happened on sample 05 and on a plain hello prompt. With mode `monitor`, sample 05 returned HTTP 200 and header `Otari-Guardrails` `[{"profile":"prompt-injection","mode":"monitor","valid":null,"score":null}]`, which means the check was not evaluated. The client now reports a 5xx whose detail mentions a guardrail, when guardrails are sent, as status `error` with code `guardrail_upstream_error`. It is not retried on the fallback model, and it is never counted as a block, flag, or quarantine. Open upstream question (owner: Alex Suarez): how a hosted workspace enables the guardrails service, or which `url` a guardrail entry should name. This checkout's tests stay offline.

## Rubric

### Open-weight models, two roles

| Role | Model id | Vendor | Code |
| --- | --- | --- | --- |
| Extractor | `alibaba/qwen3-235b-a22b-instruct-2507` | Alibaba | `demo/config.py` `EXTRACTOR_MODEL`, called from `demo/pipeline.py` before validation |
| Repairer | `mistralai/mistral-small-3.2-24b-instruct-2506` | Mistral | `demo/config.py` `REPAIRER_MODEL`, called only after AISchemaGate reports violations |

The repairer is a different vendor from the extractor. The pipeline does not use `LLMGate` auto-repair, because that would call the same client and the same model again. `LLMGate` is still constructed with the caller's OpenAI-compatible client and performs `validate_only`.

Client-side backup, not a third product role: `openai/gpt-oss-120b`.

### Features the running code exercises

| Feature | Exercised by | Unverified |
| --- | --- | --- |
| Distinct model roles | Two model lists in `demo/pipeline.py`. A hosted run used Qwen, then Mistral, and repaired. | None for the two roles themselves. |
| Routing / fallback | Live default sends `wilding-extractor` / `wilding-repairer`. `--direct-models` and sample 03 send a vendor/model id, then `openai/gpt-oss-120b` at `max_tokens` 2048. | None for the policy names: both returned HTTP 200 on 2026-10-30 12:25 PM ET (DeepInfra Qwen3, OVHcloud Mistral). Client-side fallback was already live-verified. |
| Budget cap | Short sample files. Role `max_tokens` default 256, clamp 512. Client-side gpt-oss uses 2048. Budget-shaped 402/403/429 stops the run. | Whether `wilding-workspace-ceiling` ($2 monthly via `wilding-cap`) or `wilding-member-cap` ($1) rejects a call. Both are dashboard-configured. |
| Per-user budgets | `user` is omitted unless set. Header `Otari-End-User-Budget` when `OTARI_END_USER_BUDGET` is set. | The header. Mismatched `user` rejection is live-verified. |
| Guardrails | Default profile `wilding-prompt-injection`, mode `monitor`. Sample 05 uses mode `block`. HTTP 403 `guardrail_violation` (top-level `code` or `error.code`) is `blocked by guardrail`. The `otari-guardrails` header is printed on the report. A 5xx that mentions a guardrail is `guardrail_upstream_error`. | None for monitor and block on this profile. Monitor header example: `valid: true`, `score: 0.0`. Block body: HTTP 403, message `Request blocked by guardrail policy.`, score `1.0`. |
| MCP | `python -m demo mcp` speaks newline-delimited JSON-RPC and negotiates `protocolVersion`. The pipeline calls `validate_output`. | **Tools → MCP servers**. Stdio is not reachable from the gateway. |

### Pass, repair, quarantine

| Outcome | Rule |
| --- | --- |
| pass | First `validate_output` call accepts the extractor JSON. |
| repair | First call reports violations. The repairer returns JSON that the second call accepts. |
| quarantine | The repairer still fails the contract, the model output is not a JSON object after repair, or a guardrail blocks the note (`blocked by guardrail`). Sample 04 asks the model not to invent a missing `ticket_id`. The dry-run fixture omits it and quarantines. A live model may still pass: the 2026-10-30 12:25 PM ET policy run did, on the first extraction. Quarantine there is model-dependent, not guaranteed. |

A budget or authentication failure, or an upstream guardrail error (5xx while guardrails are sent), is status `error`. The CLI exits 1 and does not send the remaining samples. That is separate from quarantine so a cap is not reported as a bad document.

## Cheap calls

- Sample notes are one or two lines.
- Role `max_tokens` is 256 unless the operator passes a smaller value. Values above 512 are clamped. The gpt-oss fallback call uses 2048.
- `temperature` is 0. `stream` is false.
- `--dry-run` is the default path for tests and does not read `OTARI_API_KEY`.
- A guardrail block does not call the repairer.
- A budget refusal does not try the fallback model.

No latency, cost, or accuracy figure is claimed. Fixture classifications are not measurements.

## Dashboard-configured, not live-verified

Policies and the guardrail profile were shown on the 2026-10-30 12:25 PM ET run. These spend caps were not:

| Item | Exact setting |
| --- | --- |
| `wilding-cap` | $2, monthly. |
| `wilding-workspace-ceiling` | Workspace ceiling that applies `wilding-cap`. |
| `wilding-member-cap` | Member budget, $1. |

The same run's policy chains, recorded because the calls returned 200:

| Request `model` | What served it |
| --- | --- |
| `wilding-extractor` | Qwen3-235B-A22B-Instruct-2507 on DeepInfra, then gpt-oss-120b in the policy |
| `wilding-repairer` | Mistral-Small-3.2-24B on OVHcloud, then gpt-oss-120b in the policy |

`--direct-models` still sends `alibaba/qwen3-235b-a22b-instruct-2507` and `mistralai/mistral-small-3.2-24b-instruct-2506` with a client-side gpt-oss fallback.

Still unverified: hosted MCP (stdio stays local) and `OTARI_END_USER_BUDGET`. Leave `user` unset unless it is the API key's own user.

## What the tests cover

`pytest` runs without a key. It classifies the five fixtures, checks the fallback and guardrail paths, checks that a dry-run does not call `urlopen`, checks the stdio MCP process, and checks dependency licenses.
