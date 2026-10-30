import io
import json
import urllib.error

from demo.config import EXTRACTOR_MODEL, FALLBACK_MODEL
from demo.errors import BudgetExceeded, GuardrailBlocked
from demo.gate import build_gates
from demo.otari import OpenAIShape, OtariClient, urllib_transport
from demo.pipeline import FixtureTransport


def _completion(content: str, model: str = EXTRACTOR_MODEL) -> dict:
    return {
        "id": "fixture",
        "model": model,
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
    }


VALID = '{"invoice_id":"INV-1001","vendor":"Northwind","currency":"USD","total":42.5,"status":"paid"}'


class _Headers(dict):
    def items(self):
        return super().items()


class _Response:
    def __init__(self, status, body, headers=None):
        self.status = status
        self.headers = _Headers(headers or {"content-type": "application/json"})
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_urllib_transport_posts_to_otari_api_and_hides_the_key(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout=0):
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        seen["auth"] = request.get_header("Authorization")
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return _Response(200, json.dumps(_completion(VALID)).encode("utf-8"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    secret = "otk_test_do_not_print"
    transport = urllib_transport("https://otari.ai/api/v1", secret, timeout=12)
    status, _headers, body = transport(
        {"model": EXTRACTOR_MODEL, "messages": [{"role": "user", "content": "hi"}], "user": "demo-operator"},
        {"Otari-End-User-Budget": "wilding-end-user"},
    )
    assert status == 200
    assert seen["url"] == "https://otari.ai/api/v1/chat/completions"
    assert seen["timeout"] == 12
    assert seen["auth"] == "Bearer " + secret
    assert seen["body"]["user"] == "demo-operator"
    assert secret not in json.dumps(body)


def test_guardrail_403_is_not_sent_to_the_fallback(monkeypatch):
    calls = {"n": 0}

    def fake_urlopen(request, timeout=0):
        calls["n"] += 1
        raise urllib.error.HTTPError(
            request.full_url,
            403,
            "Forbidden",
            _Headers({"Otari-Error-Code": "guardrail_violation"}),
            io.BytesIO(b'{"detail":"blocked","code":"guardrail_violation"}'),
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = OtariClient(
        transport=urllib_transport("https://otari.ai/api/v1", "otk_test_do_not_print", 5),
        user="demo-operator",
        secrets=["otk_test_do_not_print"],
    )
    try:
        client.complete(
            models=[EXTRACTOR_MODEL, FALLBACK_MODEL],
            messages=[{"role": "user", "content": "hi"}],
            role="extractor",
        )
    except GuardrailBlocked as exc:
        assert exc.code == "guardrail_violation"
        assert "otk_test_do_not_print" not in str(exc)
    else:
        raise AssertionError("guardrail block was ignored")
    assert calls["n"] == 1


def test_unknown_model_400_falls_back_and_gpt_oss_gets_a_higher_cap():
    from demo.config import FALLBACK_MAX_TOKENS

    seen = []

    def transport(payload, extra_headers):
        del extra_headers
        seen.append(payload)
        if len(seen) == 1:
            return 400, {}, {"detail": "The model example/not-a-deployed-model does not exist", "code": "model_not_found"}
        return 200, {}, _completion(VALID, model=FALLBACK_MODEL)

    client = OtariClient(transport=transport, user="", max_tokens=256)
    body = client.complete(
        models=["example/not-a-deployed-model", FALLBACK_MODEL],
        messages=[{"role": "user", "content": "hi"}],
        role="extractor",
    )
    assert body["model"] == FALLBACK_MODEL
    assert "user" not in seen[0]
    assert seen[0]["max_tokens"] == 256
    assert "max_completion_tokens" not in seen[0]
    assert seen[1]["max_tokens"] == FALLBACK_MAX_TOKENS
    assert seen[1]["max_completion_tokens"] == FALLBACK_MAX_TOKENS
    assert [item.model for item in client.traces] == ["example/not-a-deployed-model", FALLBACK_MODEL]


def test_user_is_sent_only_when_set():
    seen = []

    def transport(payload, extra_headers):
        del extra_headers
        seen.append(payload)
        return 200, {}, _completion(VALID)

    OtariClient(transport=transport, user="").complete(
        models=[EXTRACTOR_MODEL],
        messages=[{"role": "user", "content": "hi"}],
        role="extractor",
    )
    OtariClient(transport=transport, user="matching-key-user").complete(
        models=[EXTRACTOR_MODEL],
        messages=[{"role": "user", "content": "hi"}],
        role="extractor",
    )
    assert "user" not in seen[0]
    assert seen[1]["user"] == "matching-key-user"


def test_budget_refusal_does_not_fall_back():
    transport = FixtureTransport(
        [{"status": 402, "body": {"detail": "budget exhausted", "code": "budget_exceeded"}}]
    )
    client = OtariClient(transport=transport, user="demo-operator")
    try:
        client.complete(
            models=[EXTRACTOR_MODEL, FALLBACK_MODEL],
            messages=[{"role": "user", "content": "hi"}],
            role="extractor",
        )
    except BudgetExceeded as exc:
        assert exc.code == "budget_exceeded"
    else:
        raise AssertionError("budget refusal was ignored")
    assert len(client.traces) == 1


def test_llmgate_completion_uses_the_otari_client():
    transport = FixtureTransport([{"status": 200, "body": _completion(VALID)}])
    client = OtariClient(transport=transport, user="customer-42", max_tokens=128)
    shape = OpenAIShape(client)
    gate = build_gates(shape)["invoice_v1"]
    result = gate.completion(
        model=EXTRACTOR_MODEL,
        messages=[{"role": "user", "content": "Extract the invoice."}],
        max_tokens=64,
        temperature=0,
        response_format={"type": "json_object"},
    )
    assert result.ok
    assert result.payload["invoice_id"] == "INV-1001"
    assert client.traces[0].model == EXTRACTOR_MODEL
    assert client.traces[0].user == "customer-42"
    assert client.traces[0].max_tokens == 64
    assert gate._llm is shape


def test_guardrail_5xx_is_upstream_error_not_block():
    from demo.errors import OtariError
    from demo.otari import guardrail_request

    detail = "guardrail profile 'prompt-injection' requested but no guardrails service is configured."
    transport = FixtureTransport([{"status": 502, "body": {"detail": detail}}])
    client = OtariClient(transport=transport, user="", guardrails=guardrail_request("prompt-injection", "block"))
    try:
        client.complete(models=[EXTRACTOR_MODEL, FALLBACK_MODEL], messages=[{"role": "user", "content": "hi"}], role="extractor")
    except GuardrailBlocked:
        raise AssertionError("an upstream guardrail failure must not be reported as a block")
    except OtariError as exc:
        assert exc.code == "guardrail_upstream_error"
    else:
        raise AssertionError("upstream guardrail error was ignored")
    assert len(client.traces) == 1
    assert client.traces[0].code == "guardrail_upstream_error"
