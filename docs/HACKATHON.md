# Hackathon notes

Demo name: Developers Wilding. Gateway: hosted Otari. Validator: AISchemaGate (`pip install aischemagate`, class `LLMGate`).

Anything marked unverified was not executed against the hosted workspace from this environment. There is no `OTARI_API_KEY` here, and no dashboard session.

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
| Distinct model roles | Two model lists in `demo/pipeline.py`. Dry-run sample `02_invoice_repair` records an extractor call and a repairer call. | Live completions |
| Routing / fallback | `OtariClient.complete` tries the next model on retryable HTTP statuses and transport errors. Sample `03_invoice_fallback` is a scripted 503 followed by the backup model. | Dashboard **Routing → Policies**. See the wallet-model caveat in the README. |
| Budget cap | Short sample files. `max_tokens` default 256, hard clamp 512. Budget-shaped 402/403/429 stops the run and does not fall back. | **Organization → Spend & Budgets** ceiling. Suggested amount `2` USD, period Monthly, on the demo workspace. |
| Per-user budgets | JSON field `user` on every chat completion. Header `Otari-End-User-Budget` when `OTARI_END_USER_BUDGET` is set. | Whether a hosted workspace key creates an end user from `user`, and whether the header assigns a budget. The header is documented on the self-hosted access-control page. |
| Guardrails | Request field `guardrails` with profile `prompt-injection`, mode `monitor`, `on: ["input"]`. HTTP 403 `guardrail_violation` becomes quarantine and skips the repairer. Sample `05_ticket_guardrail`. | Catalog profile name and the mandate. |
| MCP | Tool `validate_output` is how the pipeline validates. `python -m demo mcp` serves it over stdio. Tests start that process. | **Tools → MCP servers**. Hosted Otari needs an HTTPS URL. Stdio is not reachable from the gateway. |

### Pass, repair, quarantine

| Outcome | Rule |
| --- | --- |
| pass | First `validate_output` call accepts the extractor JSON. |
| repair | First call reports violations. The repairer returns JSON that the second call accepts. |
| quarantine | The repairer still fails the contract, the model output is not a JSON object after repair, or a guardrail returns `guardrail_violation`. |

A budget or authentication failure is status `error`. The CLI exits 1 and does not send the remaining samples. That is separate from quarantine so a cap is not reported as a bad document.

## Cheap calls

- Sample notes are one line.
- `max_tokens` is 256 unless the operator passes a smaller value. Values above 512 are clamped.
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
4. Per-user: send `--user demo-operator`. Create that user if the key requires an existing user (chat schema). Set `OTARI_END_USER_BUDGET` only for a service key that may assign that budget (access-control page). Not confirmed on the hosted wizard.
5. **Organization → Guardrails.** Configure `wilding-prompt-injection`, mandate `wilding-input-check` in monitor mode on the demo workspace. Align `--guardrail-profile` with the catalog if `prompt-injection` is rejected.
6. **Tools → MCP servers.** Add `aischemagate-validate` only after you have an HTTPS URL. Until then, use `python -m demo mcp` locally. Do not point the hosted gateway at a loopback address.

## What the tests cover

`pytest` runs without a key. It classifies the five fixtures, checks the fallback and guardrail paths, checks that a dry-run does not call `urlopen`, checks the stdio MCP process, and checks dependency licenses.
