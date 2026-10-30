"""OpenAI-compatible client for the hosted Otari gateway.

The same ``complete`` path serves live calls and fixture replay. Live calls
read ``OTARI_API_KEY`` inside the transport and never place it on a trace.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

from demo.config import (
    DEFAULT_BASE_URL,
    DEFAULT_GUARDRAIL_MODE,
    DEFAULT_GUARDRAIL_PROFILE,
    DEFAULT_MAX_TOKENS,
    FALLBACK_MODEL,
    MAX_TOKENS_LIMIT,
)
from demo.errors import (
    BudgetExceeded,
    FallbackExhausted,
    GuardrailBlocked,
    OtariError,
    RetryableModelError,
    public_message,
)

# status, response headers, JSON body
Transport = Callable[[dict[str, Any], dict[str, str]], tuple[int, dict[str, str], dict[str, Any]]]

_RETRYABLE_STATUS = {404, 408, 409, 429, 500, 502, 503, 504}


@dataclass
class CallTrace:
    role: str
    model: str
    status: int
    attempt: int
    user: str
    max_tokens: int
    guardrail_profiles: list[str]
    end_user_budget_set: bool
    mcp_server_ids: list[str]
    mcp_server_names: list[str]
    code: str = ""


@dataclass
class OtariClient:
    """Sends chat completions and walks a caller-supplied model list on retryable failures."""

    transport: Transport
    user: str
    max_tokens: int = DEFAULT_MAX_TOKENS
    guardrails: list[dict[str, Any]] | None = None
    end_user_budget: str = ""
    mcp_server_ids: list[str] = field(default_factory=list)
    mcp_servers: list[dict[str, Any]] = field(default_factory=list)
    secrets: list[str] = field(default_factory=list)
    traces: list[CallTrace] = field(default_factory=list)

    def complete(
        self,
        *,
        models: list[str],
        messages: list[dict[str, str]],
        role: str,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        if not models:
            raise OtariError("A role needs at least one model id.", status=0, code="no_model")
        tokens = self.max_tokens if max_tokens is None else clamp_max_tokens(max_tokens)
        failures: list[str] = []
        for attempt, model in enumerate(models, start=1):
            payload = self._payload(model, messages, tokens)
            extra_headers: dict[str, str] = {}
            if self.end_user_budget:
                extra_headers["Otari-End-User-Budget"] = self.end_user_budget
            try:
                status, headers, body = self.transport(payload, extra_headers)
            except RetryableModelError as exc:
                failures.append(f"{model}: {public_message(exc, self.secrets)}")
                self._trace(role, model, 0, attempt, tokens, code=exc.code or "transport")
                continue
            code = _error_code(body, headers)
            self._trace(role, model, status, attempt, tokens, code=code)
            if status == 200 and isinstance(body, dict) and body.get("choices"):
                return body
            if _is_guardrail(status, code):
                detail = _error_detail(body) or "guardrail blocked the request"
                raise GuardrailBlocked(detail, status=status, code=code or "guardrail_violation")
            if _is_budget(status, code, _error_detail(body)):
                detail = _error_detail(body) or "budget refused the request"
                raise BudgetExceeded(detail, status=status, code=code or "budget")
            if status in _RETRYABLE_STATUS:
                failures.append(f"{model}: HTTP {status} {code}".strip())
                continue
            detail = _error_detail(body) or f"HTTP {status}"
            raise OtariError(detail, status=status, code=code)
        raise FallbackExhausted(failures)

    def _payload(self, model: str, messages: list[dict[str, str]], max_tokens: int) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0,
            "user": self.user,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        if self.guardrails:
            payload["guardrails"] = self.guardrails
        if self.mcp_server_ids:
            payload["mcp_server_ids"] = list(self.mcp_server_ids)
        if self.mcp_servers:
            payload["mcp_servers"] = self.mcp_servers
        return payload

    def _trace(self, role: str, model: str, status: int, attempt: int, max_tokens: int, code: str = "") -> None:
        profiles = [str(item.get("profile", "")) for item in (self.guardrails or [])]
        names = [str(item.get("name", "")) for item in self.mcp_servers]
        self.traces.append(
            CallTrace(
                role=role,
                model=model,
                status=status,
                attempt=attempt,
                user=self.user,
                max_tokens=max_tokens,
                guardrail_profiles=profiles,
                end_user_budget_set=bool(self.end_user_budget),
                mcp_server_ids=list(self.mcp_server_ids),
                mcp_server_names=names,
                code=code,
            )
        )


class OpenAIShape:
    """Object LLMGate accepts: ``llm.chat.completions.create(...)``.

    ``create`` uses the same fallback list as a direct ``complete`` call.
    """

    def __init__(self, client: OtariClient) -> None:
        self._client = client
        self.chat = _Chat(self)

    def models_for(self, model: str) -> list[str]:
        chain = [model]
        if model != FALLBACK_MODEL:
            chain.append(FALLBACK_MODEL)
        return chain


class _Chat:
    def __init__(self, parent: OpenAIShape) -> None:
        self.completions = _Completions(parent)


class _Completions:
    def __init__(self, parent: OpenAIShape) -> None:
        self._parent = parent

    def create(self, *, model: str, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        # LLMGate forwards provider kwargs. Generation length stays clamped.
        kwargs.pop("stream", None)
        override = kwargs.get("max_tokens")
        return self._parent._client.complete(
            models=self._parent.models_for(model),
            messages=messages,
            role="llm",
            max_tokens=int(override) if override is not None else None,
        )


def clamp_max_tokens(value: int) -> int:
    if value < 1:
        return 1
    if value > MAX_TOKENS_LIMIT:
        return MAX_TOKENS_LIMIT
    return value


def guardrail_request(profile: str, mode: str) -> list[dict[str, Any]] | None:
    if mode == "off" or not profile:
        return None
    if mode not in ("monitor", "block"):
        raise OtariError(f"Unknown guardrail mode {mode!r}.", status=0, code="bad_guardrail")
    return [{"profile": profile, "mode": mode, "on": ["input"]}]


def mcp_server_entry(url: str) -> dict[str, Any]:
    return {
        "name": "aischemagate-validate",
        "url": url,
        "allowed_tools": ["validate_output"],
    }


def urllib_transport(base_url: str, api_key: str, timeout: float) -> Transport:
    """POST ``{base_url}/chat/completions``. The key stays in this closure."""

    endpoint = base_url.rstrip("/") + "/chat/completions"
    secrets = [api_key]

    def send(payload: dict[str, Any], extra_headers: dict[str, str]) -> tuple[int, dict[str, str], dict[str, Any]]:
        raw = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        headers.update(extra_headers)
        request = urllib.request.Request(endpoint, data=raw, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status = getattr(response, "status", 200)
                response_headers = {k.lower(): v for k, v in response.headers.items()}
                text = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            status = exc.code
            response_headers = {k.lower(): v for k, v in exc.headers.items()} if exc.headers else {}
            text = exc.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError) as exc:
            raise RetryableModelError(
                public_message(exc, secrets),
                status=0,
                code="transport",
            ) from None
        return status, response_headers, _decode_body(text, secrets)

    return send


def _decode_body(text: str, secrets: list[str]) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        return {}
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return {"detail": public_message(RuntimeError(stripped[:300]), secrets)}
    if isinstance(parsed, dict):
        return parsed
    return {"detail": "Gateway returned a non-object JSON body."}


def _error_code(body: dict[str, Any], headers: dict[str, str]) -> str:
    header_code = headers.get("otari-error-code", "")
    if isinstance(body.get("code"), str) and body["code"]:
        return body["code"]
    error = body.get("error")
    if isinstance(error, dict) and isinstance(error.get("code"), str):
        return error["code"]
    return header_code


def _error_detail(body: dict[str, Any]) -> str:
    for key in ("detail", "message"):
        if isinstance(body.get(key), str):
            return body[key]
    error = body.get("error")
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return error["message"]
    return ""


def _is_guardrail(status: int, code: str) -> bool:
    return status == 403 and code == "guardrail_violation"


def _is_budget(status: int, code: str, detail: str) -> bool:
    if status not in (402, 403, 429):
        return False
    haystack = f"{code} {detail}".lower()
    return "budget" in haystack


def default_guardrails() -> list[dict[str, Any]] | None:
    return guardrail_request(DEFAULT_GUARDRAIL_PROFILE, DEFAULT_GUARDRAIL_MODE)


def live_client_kwargs(api_key: str, base_url: str = DEFAULT_BASE_URL, timeout: float = 30.0) -> dict[str, Any]:
    return {
        "transport": urllib_transport(base_url, api_key, timeout),
        "secrets": [api_key],
    }
