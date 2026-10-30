"""Command line: ``python -m demo run samples/`` and ``python -m demo mcp``."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from demo.config import (
    DEFAULT_BASE_URL,
    DEFAULT_GUARDRAIL_PROFILE,
    DEFAULT_MAX_TOKENS,
    DEFAULT_USER,
    UNVERIFIED,
)
from demo.gate import load_contracts
from demo.mcp_server import InProcessMcp, serve
from demo.otari import (
    OpenAIShape,
    OtariClient,
    clamp_max_tokens,
    guardrail_request,
    live_client_kwargs,
    mcp_server_entry,
)
from demo.pipeline import FixtureTransport, discover_samples, load_script, run_sample
from demo.report import render_json, render_text, summarize


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="demo",
        description="Extract structured JSON with open-weight models on Otari, then check it with AISchemaGate.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Classify each sample as pass, repair, or quarantine.")
    run.add_argument("samples", type=Path, help="Directory of sample folders.")
    run.add_argument("--dry-run", action="store_true", help="Replay fixtures. Does not call Otari.")
    run.add_argument("--fixtures", type=Path, default=Path("fixtures"), help="Fixture scripts used with --dry-run.")
    run.add_argument("--user", default=os.environ.get("OTARI_USER", DEFAULT_USER))
    run.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    run.add_argument("--base-url", default=os.environ.get("OTARI_BASE_URL", DEFAULT_BASE_URL))
    run.add_argument("--guardrail-profile", default=DEFAULT_GUARDRAIL_PROFILE)
    run.add_argument("--guardrail-mode", choices=["monitor", "block", "off"], default="monitor")
    run.add_argument("--json", action="store_true", dest="as_json")
    run.add_argument("--timeout", type=float, default=30.0)

    sub.add_parser("mcp", help="Serve the validate_output tool over stdio MCP.")

    args = parser.parse_args(argv)
    if args.command == "mcp":
        serve()
        return 0
    return _run(args)


def _run(args: argparse.Namespace) -> int:
    samples_dir: Path = args.samples
    if not samples_dir.is_dir():
        print(f"Samples directory not found: {samples_dir}", file=sys.stderr)
        return 2
    samples = discover_samples(samples_dir)
    if not samples:
        print(f"No sample folders with input.txt under {samples_dir}", file=sys.stderr)
        return 2

    api_key = os.environ.get("OTARI_API_KEY", "")
    if not args.dry_run and not api_key:
        print(
            "OTARI_API_KEY is not set. Export the workspace key or pass --dry-run.",
            file=sys.stderr,
        )
        return 2

    max_tokens = clamp_max_tokens(args.max_tokens)
    guardrails = guardrail_request(args.guardrail_profile, args.guardrail_mode)
    end_user_budget = os.environ.get("OTARI_END_USER_BUDGET", "").strip()
    mcp_server_id = os.environ.get("OTARI_MCP_SERVER_ID", "").strip()
    mcp_url = os.environ.get("OTARI_MCP_URL", "").strip()
    mcp_ids = [mcp_server_id] if mcp_server_id else []
    mcp_servers = [mcp_server_entry(mcp_url)] if mcp_url else []
    compiled = load_contracts()

    results = []
    for sample_dir in samples:
        if args.dry_run:
            try:
                script = load_script(args.fixtures, sample_dir.name)
            except (FileNotFoundError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            transport_kwargs = {"transport": FixtureTransport(script), "secrets": []}
        else:
            transport_kwargs = live_client_kwargs(api_key, args.base_url, args.timeout)
        client = OtariClient(
            user=args.user,
            max_tokens=max_tokens,
            guardrails=guardrails,
            end_user_budget=end_user_budget,
            mcp_server_ids=mcp_ids,
            mcp_servers=mcp_servers,
            **transport_kwargs,
        )
        shape = OpenAIShape(client)
        session = InProcessMcp(llm=shape)
        result = run_sample(sample_dir, client, session, compiled)
        results.append(result)
        if result.status == "error" and not args.dry_run:
            # A budget or auth failure will not succeed on the next sample.
            break

    summary = summarize(results, mode="dry-run" if args.dry_run else "live")
    summary["unverified"] = list(UNVERIFIED)
    text = render_json(summary) if args.as_json else render_text(summary)
    print(text)
    if any(item.status == "error" for item in results):
        return 1
    return 0
