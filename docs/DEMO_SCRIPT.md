# Demo script (about 2 to 3 minutes)

Outline for a screen recording. Do not read numbers that this repo did not measure. If the recording uses `--dry-run`, say the model replies are authored fixtures, not a live capture. If you switch to a live call, say that the dashboard steps were done in the account and that this repository's own test run did not verify them.

## 0:00–0:20 — The problem

Show `samples/02_invoice_repair/input.txt`.

One sentence: a note like "charged -12, currency usd, status pending" is not something a downstream system should store. The extractor writes JSON. AISchemaGate decides whether that JSON matches the contract.

## 0:20–0:45 — The path

Show the mermaid diagram in the README, or the roles table.

- Extractor: `alibaba/qwen3-235b-a22b-instruct-2507`
- Check: MCP tool `validate_output`, which calls AISchemaGate `LLMGate`
- Repairer, different vendor: `mistralai/mistral-small-3.2-24b-instruct-2506`
- If the role model returns a retryable error, the client tries `openai/gpt-oss-120b`
- Outcomes: pass, repair, quarantine

## 0:45–1:35 — Dry-run in the terminal

```bash
python -m demo run samples/ --dry-run
```

Point at four lines, one each:

- `01_invoice_pass` — first check accepted the JSON
- `02_invoice_repair` — in dry-run, currency, total, and status failed and the repairer output passed (live: one run repaired a negative total; a later run passed on the first extraction)
- `03_invoice_fallback` — primary id `example/not-a-deployed-model`, then `openai/gpt-oss-120b` (dry-run replays 404, then a valid invoice; live, the unknown id returned HTTP 400 `invalid_model` and gpt-oss answered)
- `04_ticket_quarantine` — the note has no ticket number, and the repairer is told not to invent `ticket_id` (live: quarantined on `ticket_id`)
- `05_ticket_guardrail` — prompt injection with guardrail mode `block` (dry-run replays HTTP 403. Live, the gateway returned HTTP 502 "no guardrails service is configured" and the demo reports an upstream guardrail error. Do not call it a block)

Say: these five replies were written into `fixtures/` so the demo runs with no API key and no spend. They are not a benchmark.

## 1:35–2:20 — Dashboard-configured, not yet shown on a call

Say these exist in the dashboard and that this recording has not shown a completion using them, unless you just did.

- `wilding-extractor`: Qwen3-235B-A22B-Instruct-2507 on DeepInfra, then gpt-oss-120b. Live runs send that name as `model`.
- `wilding-repairer`: Mistral-Small-3.2-24B on OVHcloud, then gpt-oss-120b.
- `wilding-cap` is $2 monthly, workspace ceiling `wilding-workspace-ceiling`. Member budget `wilding-member-cap` is $1.
- Guardrail `wilding-prompt-injection` (Lakera Guard) is pending. The client sends that profile. A block has not been observed.
- `user` stays unset unless it matches the API key.

## 2:20–2:45 — MCP

In a second terminal, you can show the tool exists:

```bash
python -m pytest -q tests/test_mcp.py
```

Or describe it: `python -m demo mcp` serves `validate_output` on stdio, and the pipeline calls that same tool. Hosted Otari can attach only an HTTPS server it can reach. That attachment is not part of the dry-run.

## 2:45–3:00 — Close

Repeat the three outcomes. Point at `OTARI_API_KEY` in `.env.example` and say the key stays in the shell. A live command, when the key exists, is:

```bash
export OTARI_API_KEY="…"
python -m demo run samples/
```

Stop there. Do not quote token totals, dollar totals, or accuracy.
