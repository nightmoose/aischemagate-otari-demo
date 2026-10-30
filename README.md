# Developers Wilding

Messy invoices and support notes go in. A JSON object that matches a contract comes out, or the note is quarantined.

An extractor model on the hosted [Otari](https://otari.ai) gateway turns the note into JSON. [AISchemaGate](https://www.aischemagate.dev/docs/llm-sdk-reference) (`LLMGate` from `aischemagate`) checks types, enums, and ranges. When the check fails, a repairer model from a different vendor rewrites the JSON and the check runs again. Each note is reported as **pass**, **repair**, or **quarantine**.

Live calls use the workspace key in `OTARI_API_KEY`. That value is read at runtime and is never written by this repo. `--dry-run` replays authored fixtures and does not call Otari, so tests run without the key.

Live chat completions, the dashboard routing policy, hosted MCP, a hosted guardrail mandate, and the hosted per-user budget header are unverified. They were not live-verified. An unauthenticated probe on 2026-10-30 checked the URL shape only: `GET https://otari.ai/api/v1/models` returned HTTP 401, and `GET https://api.otari.ai/v1/models` returned HTTP 404 telling the client to use `/api/v1`.

## Architecture

```mermaid
flowchart TD
  note[Messy invoice or ticket]
  note --> extractor[Extractor role]
  extractor --> otari[Otari chat completions]
  otari -->|retryable failure| fallback[Client fallback openai/gpt-oss-120b]
  fallback --> otari
  otari -->|403 guardrail_violation| quarantine[quarantine]
  otari --> mcp[MCP tool validate_output]
  mcp --> gate[AISchemaGate LLMGate]
  gate -->|ok| pass[pass]
  gate -->|violations| repairer[Repairer role]
  repairer --> otari2[Otari chat completions]
  otari2 --> mcp2[MCP tool validate_output]
  mcp2 --> gate2[AISchemaGate LLMGate]
  gate2 -->|ok| repair[repair]
  gate2 -->|still failing| quarantine
```

Roles:

| Role | Model id | Vendor |
| --- | --- | --- |
| Extractor | `alibaba/qwen3-235b-a22b-instruct-2507` | Alibaba |
| Repairer | `mistralai/mistral-small-3.2-24b-instruct-2506` | Mistral |
| Client-side fallback for either role | `openai/gpt-oss-120b` | OpenAI |

Model ids are the plain `vendor/model` form. Each request sets `max_tokens` (default 256, clamped at 512), `temperature` 0, and `response_format` `json_object`.

Validation is `LLMGate.validate_only`, reached through the MCP tool `validate_output`. The gate is constructed with the caller's OpenAI-compatible client (`llm=`). The check runs in-process on the engine installed with `aischemagate`. The hosted AISchemaGate egress API was not called.

## Quickstart

```bash
python -m pip install -e ".[dev]"
python -m demo run samples/ --dry-run
pytest -q
```

Live run, after the dashboard steps below:

```bash
export OTARI_API_KEY="paste-the-workspace-key-here"
python -m demo run samples/ --user demo-operator
```

Do not commit the key. `.env.example` lists the variable names with empty values.

Other entry points:

```bash
python -m demo run samples/ --dry-run --json
python -m demo mcp
```

`python -m demo mcp` speaks stdio MCP and exposes `validate_output`.

## Otari features used

Judges should score a feature only where this repo actually exercises it. "Live-verified" means a successful authenticated call or a dashboard click from this environment. None of those were done here.

| Feature | What the code does | Where | Live-verified |
| --- | --- | --- | --- |
| Distinct model roles | Extractor and repairer are different open-weight ids from different vendors. Each sample names one role, then the other only after a contract violation. | `demo/config.py`, `demo/pipeline.py` (`extractor_models`, `repairer_models`) | No |
| Routing / fallback | `OtariClient.complete` walks the role's model list. Retryable statuses are 404, 408, 409, 429, 500, 502, 503, 504, and transport errors. A guardrail 403 and a budget refusal are not retried. The backup id is `openai/gpt-oss-120b`. Sample `03_invoice_fallback` replays HTTP 503 then a success from the backup. | `demo/otari.py`, `fixtures/03_invoice_fallback/script.json` | No. Dashboard policy not applied. |
| Budget cap | Inputs are a few lines. `max_tokens` defaults to 256 and is clamped to 512. A body whose code or detail contains `budget` on HTTP 402, 403, or 429 raises `BudgetExceeded` and the run stops. | `demo/config.py`, `demo/otari.py`, `demo/cli.py` | No |
| Per-user attribution | Every chat completion sends the OpenAI `user` field (`--user`, default `demo-operator`). When `OTARI_END_USER_BUDGET` is set, the client also sends header `Otari-End-User-Budget`. | `demo/otari.py` `_payload` | No |
| Guardrails | Every request sends `guardrails: [{profile, mode, on: [input]}]` unless `--guardrail-mode off`. Default profile `prompt-injection`, mode `monitor`. HTTP 403 with code `guardrail_violation` (body or `Otari-Error-Code`) quarantines the note and does not call the repairer. Sample `05_ticket_guardrail` replays that response. | `demo/otari.py`, `fixtures/05_ticket_guardrail/script.json` | No |
| MCP | Tool `validate_output` is the validation path the pipeline calls, via the same JSON-RPC handler as `python -m demo mcp` (stdio, Content-Length framing). Hosted Otari needs a Streamable HTTP URL it can reach. This stdio server is not that URL. If `OTARI_MCP_SERVER_ID` or `OTARI_MCP_URL` is set, the chat body also includes `mcp_server_ids` or `mcp_servers`. | `demo/mcp_server.py`, `demo/pipeline.py` | No |

## Dashboard setup still required

These clicks are the operator's job. This environment did not perform them. Labels match the hosted how-to pages read from docs.otari.ai on 2026-10-30. Where a page did not name a control, this list does not invent one.

### API key

1. Open the workspace (top-left).
2. Open **API Keys**.
3. Click **Create Key**. Copy the token once. It is shown only then.
4. Export it as `OTARI_API_KEY` in the shell. Do not put it in the repo.

The published quickstart still shows `https://api.otari.ai/v1`. The live host probe above answered that path with HTTP 404 and said to use `/api/v1`. This client posts to `https://otari.ai/api/v1/chat/completions`. Override with `--base-url` or `OTARI_BASE_URL` if your workspace documents a different origin.

Confirm a call, when you make one, on the workspace **Usage** tab. This repo has not seen that tab.

### Routing policy

From [Create a multi-provider routing](https://docs.otari.ai/how-to-guides/create-a-multi-provider-routing):

1. Open the target workspace.
2. Open **Routing**.
3. Click **Policies**.
4. Name the policy `wilding-extractor`.
5. Choose **Add a fallback chain**.
6. First entry: `alibaba/qwen3-235b-a22b-instruct-2507`. Second entry: `openai/gpt-oss-120b`.
7. Click **Create policy**.
8. Create `wilding-repairer` the same way. First entry: `mistralai/mistral-small-3.2-24b-instruct-2506`. Second entry: `openai/gpt-oss-120b`.

The same guide says a routing policy routes across **your** provider keys. Wallet-billed models are served when the request names one model directly. A policy entry with no provider key of yours is skipped, and a request whose entries all fail that way is refused with `managed_credential_unsupported`. This demo therefore names each role model on the request and does client-side fallback. Create the policies if the workspace has provider keys for those models. With only the hosted wallet, do not expect the policy to replace the model id. That interaction was not live-verified.

### Budget cap and per-user budgets

Account cap, from [Set a budget & ceiling](https://docs.otari.ai/how-to-guides/set-a-budget-and-ceiling). A budget does not block requests until a spend ceiling uses it.

1. Open **Organization** and select **Spend & Budgets**.
2. Click **Add budget**.
3. Name: `wilding-cap`. Amount: `2` (USD). Period: **Monthly**.
4. Click **Add budget**.
5. Click **Add ceiling**.
6. Capping: the demo workspace (the wizard offers the whole organization or one workspace).
7. Provider instance: leave blank so the ceiling covers every provider.
8. Budget: `wilding-cap`.
9. Name: `wilding-workspace-ceiling`.
10. Click **Add ceiling**.

The concepts page at `otari.ai/docs/hosted/concepts/budgets` also describes a member scope ("all members, or one specific member"). The ceiling wizard text on docs.otari.ai does not include a member picker. If the dashboard you open shows a member control, add a second ceiling for the member that owns the API key, with an amount no higher than the workspace ceiling. That control was not confirmed.

Per-user attribution on the request:

- The chat schema (`docs.otari.ai/api-reference/chat.md`) documents a `user` string. With an API key, that user must exist; omitting `user` bills the shared default user. This client always sends `user`.
- The self-hosted access-control page (`docs.otari.ai/otari/for-operators/access-control.md`) documents service keys: the first request that carries a new `user` creates an end user, and header `Otari-End-User-Budget` selects the budget at creation time. Later requests keep the budget already stored. That page is the operator guide, not the hosted Spend & Budgets wizard. Set `OTARI_END_USER_BUDGET` only after the key is a service key that is allowed to assign that budget. The header's effect on hosted otari.ai was **not live-verified**.

Exact error code for an exhausted ceiling was not in the pages read. The client treats HTTP 402, 403, or 429 as a budget stop when the code or detail contains `budget`, and it does not try the fallback model.

### Guardrails

From [Manage guardrails](https://docs.otari.ai/how-to-guides/manage-guardrails):

1. Open **Organization → Guardrails**.
2. Click **Configure guardrail**.
3. Pick a risk type the wizard lists (bias, hallucination, content safety, PII, or toxicity) and a catalog guardrail for a prompt-injection style check if the catalog offers one.
4. Name it `wilding-prompt-injection`.
5. API key: enter `None` to use the guardrail's environment variable, or paste the credential the wizard asks for.
6. Click **Configure guardrail**.
7. Click **Mandate a guardrail**.
8. Choose the catalog guardrail you just configured.
9. Check name: `wilding-input-check`.
10. Start in **monitor**. Move to **block** when you want refusals. If the guardrail cannot run, choose refuse only after you switch to block (the page says only blocking mandates can refuse).
11. Select the demo workspace.
12. Click **Mandate a guardrail**.

The client sends:

```json
"guardrails": [{"profile": "prompt-injection", "mode": "monitor", "on": ["input"]}]
```

`prompt-injection` is the profile name used in the gateway routing docs. Whether this workspace's catalog accepts that string was **not live-verified**. If a live call rejects the profile, pass `--guardrail-profile` with the check name from the mandate, or `--guardrail-mode off` to omit the field. A mandate can still run when the field is omitted.

A blocked call is documented as HTTP 403, header `Otari-Error-Code: guardrail_violation`, body `{"detail": "...", "code": "guardrail_violation"}`. The client quarantines that response. That shape was read from the docs, not observed from a live call.

### MCP

From [Add an MCP server](https://docs.otari.ai/tools/add-an-mcp-server):

1. Select the workspace.
2. Open **Tools → MCP servers**.
3. Click **Add MCP server**.
4. Name: `aischemagate-validate`.
5. URL: an HTTPS endpoint Otari's gateway can reach. The stdio command `python -m demo mcp` is not a URL and cannot be entered here.
6. Allowed tools: `validate_output`.
7. Leave **Enabled** on.
8. Click **Add MCP server**.

Copy the saved server id into `OTARI_MCP_SERVER_ID` if you want requests to include `mcp_server_ids`. Put a public HTTPS URL in `OTARI_MCP_URL` if you want inline `mcp_servers`. Neither variable is set by default, and neither path was live-verified.

What does run: the pipeline calls `validate_output` through the local MCP handler, and `python -m demo mcp` serves that tool on stdio. Tests drive the stdio process.

## Samples and fixtures

| Sample | Contract | Dry-run classification |
| --- | --- | --- |
| `01_invoice_pass` | `invoice_v1` | pass |
| `02_invoice_repair` | `invoice_v1` | repair (currency, total, status) |
| `03_invoice_fallback` | `invoice_v1` | pass after a scripted HTTP 503 |
| `04_ticket_quarantine` | `ticket_v1` | quarantine (priority still illegal after repair) |
| `05_ticket_guardrail` | `ticket_v1` | quarantine (`guardrail_violation`) |

Fixtures under `fixtures/` are authored stand-ins for the gateway JSON shape. They are not captures of live model output. Counts printed by the CLI are how this run classified those inputs. They are not a quality or latency measurement.

Contracts live in `demo/contracts/` and declare enums and numeric ranges. Compliance mode rejects fields the contract does not list.

## License

MIT. See `LICENSE`.

Direct dependencies are `aischemagate` (MIT) and, for tests, `pytest` (MIT). `aischemagate` installs `certifi` (MPL-2.0) and `typing_extensions` (PSF-2.0). Those two are kept only because the required package pulls them in. This repo does not import them. `tests/test_licenses.py` fails the build if a newly added distribution is outside MIT, ISC, BSD, 0BSD, or that pair of exceptions. Dual-licensed distributions are accepted when one side is MIT, ISC, BSD, or 0BSD.

## More

- Rubric map: `docs/HACKATHON.md`
- Two-to-three minute demo outline: `docs/DEMO_SCRIPT.md`
