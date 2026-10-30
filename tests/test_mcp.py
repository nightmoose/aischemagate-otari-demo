import io
import json
import subprocess
import sys

from demo.mcp_server import TOOL_NAME, InProcessMcp, read_message, write_message


def test_in_process_tool_rejects_a_bad_invoice():
    session = InProcessMcp()
    result = session.call_tool(
        TOOL_NAME,
        {
            "contract": "invoice_v1",
            "document": {
                "invoice_id": "A-9",
                "vendor": "Acme",
                "currency": "usd",
                "total": -12,
                "status": "pending",
            },
        },
    )
    assert result["ok"] is False
    assert {item["field"] for item in result["violations"]} >= {"currency", "total", "status"}


def test_stdio_server_lists_and_calls_the_tool():
    proc = subprocess.Popen(
        [sys.executable, "-m", "demo", "mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.stdin is not None and proc.stdout is not None
    try:
        write_message(
            proc.stdin,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}},
            },
        )
        initialized = read_message(proc.stdout)
        assert initialized is not None
        assert initialized["result"]["serverInfo"]["name"] == "aischemagate-validate"

        write_message(proc.stdin, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        write_message(proc.stdin, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        listed = read_message(proc.stdout)
        assert listed is not None
        names = [tool["name"] for tool in listed["result"]["tools"]]
        assert names == [TOOL_NAME]

        write_message(
            proc.stdin,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": TOOL_NAME,
                    "arguments": {
                        "contract": "ticket_v1",
                        "document": {
                            "ticket_id": "T-1",
                            "priority": "low",
                            "category": "billing",
                            "summary": "Cannot pay",
                        },
                    },
                },
            },
        )
        called = read_message(proc.stdout)
        assert called is not None
        body = json.loads(called["result"]["content"][0]["text"])
        assert body["ok"] is True
        assert body["payload"]["ticket_id"] == "T-1"
        proc.stdin.close()
        proc.wait(timeout=5)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        err = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
        assert "otk_" not in err


def test_framing_round_trip():
    buffer = io.BytesIO()
    write_message(buffer, {"jsonrpc": "2.0", "id": 7, "method": "ping"})
    buffer.seek(0)
    assert read_message(buffer) == {"jsonrpc": "2.0", "id": 7, "method": "ping"}
