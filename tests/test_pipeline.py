import json
import os

import pytest

from demo.cli import main
from demo.config import EXTRACTOR_MODEL, FALLBACK_MODEL, REPAIRER_MODEL


@pytest.fixture(autouse=True)
def _no_live_key(monkeypatch):
    monkeypatch.delenv("OTARI_API_KEY", raising=False)
    monkeypatch.delenv("OTARI_END_USER_BUDGET", raising=False)
    monkeypatch.delenv("OTARI_MCP_SERVER_ID", raising=False)
    monkeypatch.delenv("OTARI_MCP_URL", raising=False)


def test_dry_run_classifies_samples(capsys):
    code = main(["run", "samples", "--dry-run", "--fixtures", "fixtures", "--json", "--user", "demo-operator"])
    assert code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["mode"] == "dry-run"
    assert summary["live_otari_completions"] is False
    assert summary["live_verified"] is False
    by_name = {item["sample"]: item for item in summary["results"]}
    assert by_name["01_invoice_pass"]["status"] == "pass"
    assert by_name["02_invoice_repair"]["status"] == "repair"
    assert by_name["03_invoice_fallback"]["status"] == "pass"
    assert by_name["04_ticket_quarantine"]["status"] == "quarantine"
    assert by_name["05_ticket_guardrail"]["status"] == "quarantine"
    assert summary["counts"] == {"pass": 2, "repair": 1, "quarantine": 2, "error": 0}

    repair = by_name["02_invoice_repair"]
    assert {item["field"] for item in repair["violations_before_repair"]} >= {"currency", "total", "status"}
    assert repair["calls"][0]["model"] == EXTRACTOR_MODEL
    assert repair["calls"][1]["model"] == REPAIRER_MODEL
    assert repair["calls"][0]["max_tokens"] == 256
    assert repair["calls"][0]["user"] == "demo-operator"
    assert repair["calls"][0]["guardrail_profiles"] == ["prompt-injection"]

    fallback = by_name["03_invoice_fallback"]
    assert [call["model"] for call in fallback["calls"]] == [EXTRACTOR_MODEL, FALLBACK_MODEL]
    assert [call["status"] for call in fallback["calls"]] == [503, 200]

    blocked = by_name["05_ticket_guardrail"]
    assert blocked["reason"] == "guardrail:guardrail_violation"
    assert len(blocked["calls"]) == 1
    assert blocked["calls"][0]["model"] == EXTRACTOR_MODEL


def test_dry_run_does_not_touch_the_network(monkeypatch, capsys):
    def explode(*_args, **_kwargs):
        raise AssertionError("dry-run opened a socket")

    monkeypatch.setattr("urllib.request.urlopen", explode)
    monkeypatch.setenv("OTARI_API_KEY", "otk_test_do_not_print")
    code = main(["run", "samples", "--dry-run", "--fixtures", "fixtures"])
    captured = capsys.readouterr()
    assert code == 0
    assert "otk_test_do_not_print" not in captured.out
    assert "otk_test_do_not_print" not in captured.err
    assert "pass" in captured.out
    assert "repair" in captured.out
    assert "quarantine" in captured.out


def test_live_mode_requires_a_key(capsys):
    code = main(["run", "samples"])
    captured = capsys.readouterr()
    assert code == 2
    assert "OTARI_API_KEY" in captured.err


def test_budget_header_and_mcp_fields_are_on_the_request(monkeypatch, capsys):
    monkeypatch.setenv("OTARI_END_USER_BUDGET", "wilding-end-user")
    monkeypatch.setenv("OTARI_MCP_SERVER_ID", "11111111-1111-1111-1111-111111111111")
    monkeypatch.setenv("OTARI_MCP_URL", "https://mcp.example.com/validate")
    code = main(["run", "samples", "--dry-run", "--fixtures", "fixtures", "--json"])
    assert code == 0
    summary = json.loads(capsys.readouterr().out)
    call = summary["results"][0]["calls"][0]
    assert call["end_user_budget_set"] is True
    assert call["mcp_server_ids"] == ["11111111-1111-1111-1111-111111111111"]
    assert call["mcp_server_names"] == ["aischemagate-validate"]


def test_max_tokens_is_clamped(capsys):
    code = main(["run", "samples", "--dry-run", "--fixtures", "fixtures", "--json", "--max-tokens", "99999"])
    assert code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["results"][0]["calls"][0]["max_tokens"] == 512
