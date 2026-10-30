# Hackathon notes

Demo name: Developers Wilding. Gateway: hosted Otari. Validator: AISchemaGate (`pip install aischemagate`, class `LLMGate`).

Hosted runs verified chat completions, both open-weight roles, a repair, a fallback from an unknown model id to `openai/gpt-oss-120b`, a quarantine on sample 04, acceptance of the `guardrails` field in monitor mode, and rejection of a mismatched `user` (the field is omitted unless it is set). A guardrail block or flag was not observed. Items marked unverified were not part of those runs.

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
| Routing / fallback | Sample `03_invoice_fallback` calls `example/not-a-deployed-model`, then `openai/gpt-oss-120b` with `max_tokens` 2048. Unknown-model 400/404/422 responses are retryable. | Dashboard **Routing → Policies**. The client-side fallback is live-verified (HTTP 400 `invalid_model`, then gpt-oss answered). |
| Budget cap | Short sample files. Role `max_tokens` default 256, clamp 512. Fallback model uses 2048. Budget-shaped 402/403/429 stops the run. | **Organization → Spend & Budgets** ceiling. |
| Per-user budgets | `user` is omitted unless set. Header `Otari-End-User-Budget` when `OTARI_END_USER_BUDGET` is set. | The header. Mismatched `user` rejection is live-verified. |
| Guardrails | Default mode `monitor`. Sample `05_ticket_guardrail` uses mode `block` on a prompt-injection note. Block (HTTP 403) and flag (200 with a guardrail flag) both quarantine. | A live block or flag, and the dashboard mandate. Monitor was accepted but returned `valid: null`. Block returned HTTP 502 "no guardrails service is configured", reported as `guardrail_upstream_error`. |
| MCP | `python -m demo mcp` speaks newline-delimited JSON-RPC and negotiates `protocolVersion`. The pipeline calls `validate_output`. | **Tools → MCP servers**. Stdio is not reachable from the gateway. |

### Pass, repair, quarantine

| Outcome | Rule |
| --- | --- |
| pass | First `validate_output` call accepts the extractor JSON. |
| repair | First call reports violations. The repairer returns JSON that the second call accepts. |
| quarantine | The repairer still fails the contract, the model output is not a JSON object after repair, or a guardrail blocks or flags the note. Sample `04` omits `ticket_id` because the source has no ticket number, and the repairer is told not to invent it. |

A budget or authentication failure, or an upstream guardrail error (5xx while guardrails are sent), is status `error`. The CLI exits 1 and does not send the remaining samples. That is separate from quarantine so a cap is not reported as a bad document.

## Cheap calls

- Sample notes are one or two lines.
- Role `max_tokens` is 256 unless the operator passes a smaller value. Values above 512 are clamped. The gpt-oss fallback call uses 2048.
- `temperature` is 0. `stream` is false.
- `--dry-run` is the default path for tests and does not read `OTARI_API_KEY`.
- A guardrail block does not call the repairer.
- A budget refusal does not try the fallback model.

No latency, cost, or accuracy figure is claimed. Fixture classifications are not measurements.

## Dashboard steps still required

Copied in short form. The README has the click labels.

1. **API Keys → Create Key.** Export `OTARI_API_KEY`. Base URL `https://otari.ai/api/v1`.
2. **Routing → Policies.** Fallback chains `wilding-extractor` and `wilding-repairer` as in the README, only if provider keys exist for those models. Wallet-billed calls name the model id directly. Client-side fallback still runs.
3. **Organization → Spend & Budgets.** Budget `wilding-cap`, amount `2`, period Monthly. Ceiling on the demo workspace, all providers, named `wilding-workspace-ceiling`.
4. Per-user: leave `user` unset unless it is the API key's own user. A mismatched value was rejected on a hosted run. Set `OTARI_END_USER_BUDGET` only for a service key that may assign that budget (access-control page). The header is unverified on the hosted wizard.
5. **Organization → Guardrails.** Configure `wilding-prompt-injection`, mandate `wilding-input-check` on the demo workspace. The client already sends profile `prompt-injection`; that field was accepted. Sample 05 sends mode `block`. A live block or flag has not been observed: block mode returned HTTP 502 because no guardrails service is configured (open upstream question, owner Alex Suarez).
6. **Tools → MCP servers.** Add `aischemagate-validate` only after you have an HTTPS URL. Until then, use `python -m demo mcp` locally. Do not point the hosted gateway at a loopback address.

## What the tests cover

`pytest` runs without a key. It classifies the five fixtures, checks the fallback and guardrail paths, checks that a dry-run does not call `urlopen`, checks the stdio MCP process, and checks dependency licenses.
