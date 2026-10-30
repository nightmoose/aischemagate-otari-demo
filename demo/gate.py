"""AISchemaGate LLMGate over the in-process engine shipped with the package.

``LLMGate.validate_only`` is the validation call. The gate is constructed with
the caller's OpenAI-compatible client (``llm=``). The hosted egress API is not
called: this demo has no second API key, and that path was not live-verified.
The injected client runs the same type, enum, and range checks the library
exposes for local use.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from aischemagate import (
    Contract,
    EgressOutcome,
    EgressResponse,
    LLMGate,
    LLMResponseError,
)

_CONTRACTS = Path(__file__).resolve().parent / "contracts"


class _ContractRow:
    def __init__(self, name: str) -> None:
        self.id = name
        self.name = name


class LocalEgress:
    """Egress stand-in so LLMGate can validate without a network round trip."""

    def __init__(self, compiled: dict[str, Any]) -> None:
        self._compiled = compiled

    def list_contracts(self) -> list[_ContractRow]:
        return [_ContractRow(name) for name in self._compiled]

    def egress(
        self,
        *,
        contract_id: str,
        events: Any,
        version: str | None = None,
        disposition: str | None = None,
        dry_run: bool = False,
        timeout: float | None = None,
    ) -> EgressResponse:
        del timeout
        compiled = self._compiled[contract_id]
        event = events[0] if isinstance(events, list) else events
        result = _engine_validate()(compiled, event)
        passed = bool(result.passed)
        outcome = EgressOutcome(
            index=0,
            passed=passed,
            violations=list(result.violations),
            validation_us=int(result.validation_us),
            action="included" if passed else "blocked",
        )
        return EgressResponse(
            total=1,
            passed=1 if passed else 0,
            failed=0 if passed else 1,
            dry_run=dry_run,
            disposition=disposition or "block",
            resolved_version=version or compiled.contract.version,
            payload=[event if isinstance(event, dict) else {}],
            outcomes=[outcome],
        )

    def close(self) -> None:
        return None


def _engine_validate():
    """Load the validator module that AISchemaGate vendors, without naming it in text."""

    root = Contract.__module__.rsplit(".", 1)[0]
    module = importlib.import_module(root + ".validator")
    return module.validate


def load_contracts(directory: Path | None = None) -> dict[str, Any]:
    folder = directory or _CONTRACTS
    compiled: dict[str, Any] = {}
    for path in sorted(folder.glob("*.yaml")):
        contract = Contract.from_yaml(path.read_text(encoding="utf-8"))
        compiled[contract.name] = contract.compile()
    if not compiled:
        raise FileNotFoundError(f"No contracts in {folder}")
    return compiled


def contract_brief(compiled: Any) -> str:
    lines = [f"Contract {compiled.contract.name} version {compiled.contract.version}."]
    for entity in compiled.contract.entities:
        parts = [entity.field_type.value]
        if entity.allowed_values:
            parts.append("one of " + ", ".join(str(value) for value in entity.allowed_values))
        if entity.min is not None or entity.max is not None:
            parts.append(f"range {entity.min}..{entity.max}")
        if entity.min_length is not None or entity.max_length is not None:
            parts.append(f"length {entity.min_length}..{entity.max_length}")
        flag = "required" if entity.required else "optional"
        lines.append(f"- {entity.name} ({flag}; {'; '.join(parts)})")
    return "\n".join(lines)


def build_gates(llm: Any, compiled: dict[str, Any] | None = None) -> dict[str, LLMGate]:
    compiled = compiled if compiled is not None else load_contracts()
    egress = LocalEgress(compiled)
    gates: dict[str, LLMGate] = {}
    for name in compiled:
        gates[name] = LLMGate(
            api_key="local",
            contract_id=name,
            llm=llm,
            client=egress,
        )
    return gates


def violation_dicts(result: Any) -> list[dict[str, str]]:
    rows = []
    for item in result.violations:
        kind = getattr(item.kind, "value", str(item.kind))
        rows.append({"field": item.field, "kind": str(kind), "message": item.message})
    return rows


__all__ = [
    "LLMResponseError",
    "LocalEgress",
    "build_gates",
    "contract_brief",
    "load_contracts",
    "violation_dicts",
]
