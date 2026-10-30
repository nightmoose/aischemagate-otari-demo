"""Local MCP server (stdio) exposing AISchemaGate validation as ``validate_output``.

Hosted Otari reaches MCP servers over Streamable HTTP from the gateway. This
process speaks stdio, so the hosted workspace cannot call it. The pipeline
uses the same JSON-RPC handler in-process. That local use is what runs.
Attaching a workspace server in the dashboard was not live-verified.
"""

from __future__ import annotations

import json
import sys
from typing import Any, BinaryIO

from aischemagate import LLMResponseError

from demo.gate import build_gates, violation_dicts

PROTOCOL_VERSION = "2025-06-18"
TOOL_NAME = "validate_output"


def tool_definition() -> dict[str, Any]:
    return {
        "name": TOOL_NAME,
        "description": (
            "Validate one JSON document against an AISchemaGate contract. "
            "Returns ok plus any type, enum, or range violations."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["contract", "document"],
            "properties": {
                "contract": {
                    "type": "string",
                    "description": "Contract name, for example invoice_v1 or ticket_v1.",
                },
                "document": {
                    "description": "A JSON object, a JSON string, or a chat-completion object.",
                },
            },
        },
    }


class ToolContext:
    def __init__(self, llm: Any | None = None) -> None:
        self.gates = build_gates(llm)


def dispatch(message: dict[str, Any], context: ToolContext) -> dict[str, Any] | None:
    method = message.get("method")
    msg_id = message.get("id")
    if method == "notifications/initialized" or method == "initialized":
        return None
    if msg_id is None and isinstance(method, str) and method.startswith("notifications/"):
        return None
    try:
        result = _call(method, message.get("params") or {}, context)
    except _RpcError as exc:
        if msg_id is None:
            return None
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": exc.code, "message": exc.message}}
    if msg_id is None:
        return None
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _call(method: Any, params: dict[str, Any], context: ToolContext) -> Any:
    if method == "initialize":
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "aischemagate-validate", "version": "0.1.0"},
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": [tool_definition()]}
    if method == "tools/call":
        return _tools_call(params, context)
    raise _RpcError(-32601, f"Unknown method: {method}")


def _tools_call(params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    name = params.get("name")
    arguments = params.get("arguments") or {}
    if name != TOOL_NAME:
        raise _RpcError(-32602, f"Unknown tool: {name}")
    contract = arguments.get("contract")
    if not isinstance(contract, str) or contract not in context.gates:
        known = ", ".join(sorted(context.gates))
        return _tool_error(f"Unknown contract {contract!r}. Known contracts: {known}.")
    if "document" not in arguments:
        return _tool_error("document is required.")
    gate = context.gates[contract]
    try:
        checked = gate.validate_only(arguments["document"])
    except LLMResponseError:
        return _tool_error("The document was not a JSON object.")
    body = {
        "ok": bool(checked.ok),
        "contract": contract,
        "violations": violation_dicts(checked),
        "payload": checked.payload if checked.ok else None,
    }
    return {
        "content": [{"type": "text", "text": json.dumps(body)}],
        "isError": False,
        "structuredContent": body,
    }


def _tool_error(message: str) -> dict[str, Any]:
    body = {"ok": False, "violations": [], "payload": None, "error": message}
    return {
        "content": [{"type": "text", "text": json.dumps(body)}],
        "isError": True,
        "structuredContent": body,
    }


class InProcessMcp:
    """Pipeline-facing session. Same handler the stdio server runs."""

    def __init__(self, context: ToolContext | None = None, llm: Any | None = None) -> None:
        self.context = context or ToolContext(llm)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        response = dispatch(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            },
            self.context,
        )
        if response is None or "error" in response:
            message = "MCP tool call failed."
            if response and "error" in response:
                message = str(response["error"].get("message", message))
            raise RuntimeError(message)
        result = response["result"]
        structured = result.get("structuredContent") or {}
        if result.get("isError"):
            raise RuntimeError(str(structured.get("error") or "MCP tool returned an error."))
        return structured


class _RpcError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def read_message(stream: BinaryIO) -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = stream.readline()
        if line == b"":
            return None
        if line in (b"\r\n", b"\n"):
            break
        if b":" not in line:
            continue
        key, value = line.split(b":", 1)
        headers[key.decode("ascii", errors="replace").strip().lower()] = value.decode(
            "ascii", errors="replace"
        ).strip()
    if "content-length" not in headers:
        return None
    length = int(headers["content-length"])
    raw = stream.read(length)
    if len(raw) < length:
        return None
    parsed = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise _RpcError(-32700, "Message was not a JSON object.")
    return parsed


def write_message(stream: BinaryIO, payload: dict[str, Any]) -> None:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    header = f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii")
    stream.write(header + raw)
    stream.flush()


def serve(stdin: BinaryIO | None = None, stdout: BinaryIO | None = None) -> None:
    incoming = stdin if stdin is not None else sys.stdin.buffer
    outgoing = stdout if stdout is not None else sys.stdout.buffer
    context = ToolContext()
    while True:
        try:
            message = read_message(incoming)
        except _RpcError as exc:
            write_message(
                outgoing,
                {"jsonrpc": "2.0", "id": None, "error": {"code": exc.code, "message": exc.message}},
            )
            continue
        if message is None:
            return
        reply = dispatch(message, context)
        if reply is not None:
            write_message(outgoing, reply)
