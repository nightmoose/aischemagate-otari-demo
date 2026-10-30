"""Text and JSON reports. Counts are classifications of this run, not quality scores."""

from __future__ import annotations

import json
from typing import Any

from demo.config import LIVE_VERIFIED, UNVERIFIED
from demo.pipeline import SampleResult


def summarize(results: list[SampleResult], *, mode: str) -> dict[str, Any]:
    counts = {"pass": 0, "repair": 0, "quarantine": 0, "error": 0}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    return {
        "mode": mode,
        "live_otari_completions": mode == "live",
        "live_verified": list(LIVE_VERIFIED),
        "unverified": list(UNVERIFIED),
        "counts": counts,
        "results": [item.to_dict() for item in results],
    }


def render_text(summary: dict[str, Any]) -> str:
    lines = [
        f"mode: {summary['mode']}",
        "live Otari completions in this process: "
        + ("attempted (outcome not independently verified here)" if summary["live_otari_completions"] else "not called"),
        "",
        f"{'sample':<24} {'status':<12} {'contract':<14} detail",
    ]
    for result in summary["results"]:
        detail = " ".join(
            part for part in (result.get("reason") or "", _model_detail(result)) if part
        )
        lines.append(
            f"{result['sample']:<24} {result['status']:<12} {result['contract']:<14} {detail}"
        )
    counts = summary["counts"]
    lines.append("")
    lines.append(
        "classified: "
        f"{counts.get('pass', 0)} pass, "
        f"{counts.get('repair', 0)} repair, "
        f"{counts.get('quarantine', 0)} quarantine, "
        f"{counts.get('error', 0)} error"
    )
    lines.append("These counts describe this run's fixture or live classifications. They are not a benchmark.")
    lines.append("Live-verified on a hosted run (a dry-run does not re-check them):")
    for item in summary.get("live_verified") or []:
        lines.append(f"- {item}")
    lines.append("Still unverified:")
    for item in summary.get("unverified") or []:
        lines.append(f"- {item}")
    return "\n".join(lines)


def render_json(summary: dict[str, Any]) -> str:
    return json.dumps(summary, indent=2)


def _model_detail(result: dict[str, Any]) -> str:
    calls = result.get("calls") or []
    if not calls:
        return ""
    parts = [f"{call['role']}={call['model']}@{call['status']}" for call in calls]
    return " ".join(parts)
