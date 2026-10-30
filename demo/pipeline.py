"""Extractor, AISchemaGate check, repairer, second check.

Outcomes are pass, repair, or quarantine. A guardrail block is quarantine
and does not call the repairer. A budget refusal stops the sample with
status ``error`` so later samples are not sent.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from demo.config import EXTRACTOR_MODEL, FALLBACK_MODEL, REPAIRER_MODEL
from demo.errors import BudgetExceeded, FallbackExhausted, GuardrailBlocked, OtariError, public_message
from demo.gate import contract_brief, load_contracts
from demo.mcp_server import TOOL_NAME, InProcessMcp
from demo.otari import OtariClient

_SOURCE_LIMIT = 4000


@dataclass
class SampleResult:
    sample: str
    status: str
    contract: str
    reason: str = ""
    violations_before_repair: list[dict[str, str]] = field(default_factory=list)
    violations_after_repair: list[dict[str, str]] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def extractor_models() -> list[str]:
    return [EXTRACTOR_MODEL, FALLBACK_MODEL]


def repairer_models() -> list[str]:
    return [REPAIRER_MODEL, FALLBACK_MODEL]


def discover_samples(samples_dir: Path) -> list[Path]:
    found = [path for path in samples_dir.iterdir() if path.is_dir() and (path / "input.txt").is_file()]
    return sorted(found, key=lambda path: path.name)


def load_script(fixtures_dir: Path, sample_name: str) -> list[dict[str, Any]]:
    path = fixtures_dir / sample_name / "script.json"
    if not path.is_file():
        raise FileNotFoundError(f"Missing fixture script {path}")
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, list):
        raise ValueError(f"Fixture script {path} must be a list.")
    return parsed


class FixtureTransport:
    """Replays an authored script. It does not open a socket."""

    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._events = list(events)

    def __call__(self, payload: dict[str, Any], extra_headers: dict[str, str]) -> tuple[int, dict[str, str], dict[str, Any]]:
        del extra_headers
        if not self._events:
            raise OtariError("Fixture script ran out of responses.", status=0, code="fixture_exhausted")
        event = self._events.pop(0)
        status = int(event["status"])
        headers = {str(k).lower(): str(v) for k, v in (event.get("headers") or {}).items()}
        body = event.get("body") or {}
        if not isinstance(body, dict):
            raise OtariError("Fixture body must be a JSON object.", status=0, code="bad_fixture")
        return status, headers, body


def run_sample(
    sample_dir: Path,
    client: OtariClient,
    session: InProcessMcp,
    compiled: dict[str, Any],
) -> SampleResult:
    name = sample_dir.name
    contract_name = (sample_dir / "contract.txt").read_text(encoding="utf-8").strip()
    if contract_name not in compiled:
        return SampleResult(sample=name, status="error", contract=contract_name, reason="unknown_contract")
    source = (sample_dir / "input.txt").read_text(encoding="utf-8").strip()
    if len(source) > _SOURCE_LIMIT:
        source = source[:_SOURCE_LIMIT]
    brief = contract_brief(compiled[contract_name])
    trace_start = len(client.traces)
    try:
        extracted = client.complete(
            models=extractor_models(),
            messages=_extract_messages(brief, source),
            role="extractor",
        )
    except GuardrailBlocked as exc:
        return _finish(
            SampleResult(
                sample=name,
                status="quarantine",
                contract=contract_name,
                reason=f"guardrail:{exc.code}",
            ),
            client,
            trace_start,
        )
    except (BudgetExceeded, FallbackExhausted, OtariError) as exc:
        return _finish(
            SampleResult(
                sample=name,
                status="error",
                contract=contract_name,
                reason=public_message(exc, client.secrets),
            ),
            client,
            trace_start,
        )

    first = _validate(session, contract_name, extracted)
    if first.get("error"):
        first_violations = [{"field": "<root>", "kind": "parse", "message": str(first["error"])}]
    elif first.get("ok"):
        return _finish(
            SampleResult(sample=name, status="pass", contract=contract_name),
            client,
            trace_start,
        )
    else:
        first_violations = list(first.get("violations") or [])

    try:
        repaired = client.complete(
            models=repairer_models(),
            messages=_repair_messages(brief, _content_text(extracted), first_violations),
            role="repairer",
        )
    except GuardrailBlocked as exc:
        return _finish(
            SampleResult(
                sample=name,
                status="quarantine",
                contract=contract_name,
                reason=f"guardrail:{exc.code}",
                violations_before_repair=first_violations,
            ),
            client,
            trace_start,
        )
    except (BudgetExceeded, FallbackExhausted, OtariError) as exc:
        return _finish(
            SampleResult(
                sample=name,
                status="error",
                contract=contract_name,
                reason=public_message(exc, client.secrets),
                violations_before_repair=first_violations,
            ),
            client,
            trace_start,
        )

    second = _validate(session, contract_name, repaired)
    if second.get("ok"):
        return _finish(
            SampleResult(
                sample=name,
                status="repair",
                contract=contract_name,
                violations_before_repair=first_violations,
            ),
            client,
            trace_start,
        )
    after = list(second.get("violations") or [])
    if second.get("error"):
        after = [{"field": "<root>", "kind": "parse", "message": str(second["error"])}]
    fields = ",".join(item.get("field", "") for item in after) or "document"
    return _finish(
        SampleResult(
            sample=name,
            status="quarantine",
            contract=contract_name,
            reason=f"contract:{fields}",
            violations_before_repair=first_violations,
            violations_after_repair=after,
        ),
        client,
        trace_start,
    )


def _validate(session: InProcessMcp, contract_name: str, document: Any) -> dict[str, Any]:
    try:
        return session.call_tool(TOOL_NAME, {"contract": contract_name, "document": document})
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc), "violations": []}


def _finish(result: SampleResult, client: OtariClient, trace_start: int) -> SampleResult:
    result.calls = [_trace_dict(item) for item in client.traces[trace_start:]]
    return result


def _trace_dict(item: Any) -> dict[str, Any]:
    return {
        "role": item.role,
        "model": item.model,
        "status": item.status,
        "attempt": item.attempt,
        "user": item.user,
        "max_tokens": item.max_tokens,
        "guardrail_profiles": list(item.guardrail_profiles),
        "end_user_budget_set": item.end_user_budget_set,
        "mcp_server_ids": list(item.mcp_server_ids),
        "mcp_server_names": list(item.mcp_server_names),
        "code": item.code,
    }


def _content_text(completion: dict[str, Any]) -> str:
    try:
        content = completion["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return ""
    return content if isinstance(content, str) else json.dumps(content)


def _extract_messages(brief: str, source: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": "Extract one JSON object that matches the contract. No prose and no markdown.",
        },
        {"role": "user", "content": brief + "\n\nText:\n" + source},
    ]


def _repair_messages(brief: str, rejected: str, violations: list[dict[str, str]]) -> list[dict[str, str]]:
    lines = ["The JSON failed the contract. Return only the corrected JSON object."]
    for item in violations:
        lines.append(f"- {item.get('field', '')}: {item.get('message', '')}")
    lines.append("Rejected JSON:")
    lines.append(rejected[:2000])
    lines.append("Fields:")
    lines.append(brief)
    return [
        {
            "role": "system",
            "content": "You repair JSON so it satisfies the contract. Output one JSON object.",
        },
        {"role": "user", "content": "\n".join(lines)},
    ]
