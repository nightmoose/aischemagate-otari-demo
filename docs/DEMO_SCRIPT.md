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
- `02_invoice_repair` — currency, total, and status failed; the repairer output passed
- `03_invoice_fallback` — primary id `example/not-a-deployed-model`, then `openai/gpt-oss-120b` (dry-run replays 404, then a valid invoice; say the live fallback has not been checked)
- `04_ticket_quarantine` — the note has no ticket number, and the repairer is told not to invent `ticket_id`
- `05_ticket_guardrail` — prompt injection with guardrail mode `block` (dry-run replays HTTP 403; a live block or flag has not been checked)

Say: these five replies were written into `fixtures/` so the demo runs with no API key and no spend. They are not a benchmark.

## 1:35–2:20 — What the account still needs

Switch to the otari.ai dashboard only if you are logged in. Otherwise leave this as a slide with the README list.

- **Routing → Policies:** fallback chains for the two roles, and the caveat that wallet models are selected by naming them on the request
- **Spend & Budgets:** budget `wilding-cap` at 2 USD monthly, ceiling on this workspace
- **Guardrails:** mandate a monitor check, then block when you want refusals
- Mention that `user` is omitted unless it matches the API key (a mismatched value was rejected) and that `Otari-End-User-Budget` is optional and unverified

If you did not click these in the recording, say they are still operator setup.

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
