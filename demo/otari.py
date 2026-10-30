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
    FALLBACK_MAX_TOKENS,
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
    guardrail_modes: list[str]
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
    guardrail_mode_locked: bool = False
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
        failures: list[str] = []
        for attempt, model in enumerate(models, start=1):
            tokens = _tokens_for(model, self.max_tokens if max_tokens is None else max_tokens)
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
            detail = _error_detail(body)
            signal = _guardrail_signal(status, code, headers, body)
            trace_code = code
            if signal == "flag" and not trace_code:
                trace_code = "guardrail_flagged"
            elif signal == "block" and not trace_code:
                trace_code = "guardrail_violation"
            if status >= 500 and self.guardrails and "guardrail" in detail.lower():
                # The gateway could not run the guardrail. That is not a block or a flag.
                self._trace(role, model, status, attempt, tokens, code="guardrail_upstream_error")
                raise OtariError(
                    f"upstream guardrail error (HTTP {status}): {detail}",
                    status=status,
                    code="guardrail_upstream_error",
                )
            self._trace(role, model, status, attempt, tokens, code=trace_code)
            if signal == "block":
                raise GuardrailBlocked(
                    detail or "guardrail blocked the request",
                    status=status,
                    code=code or "guardrail_violation",
                )
            if signal == "flag":
                raise GuardrailBlocked(
                    detail or "guardrail flagged the response",
                    status=status,
                    code="guardrail_flagged",
                )
            if status == 200 and isinstance(body, dict) and body.get("choices"):
                return body
            if _is_budget(status, code, detail):
                raise BudgetExceeded(detail or "budget refused the request", status=status, code=code or "budget")
            if status in _RETRYABLE_STATUS or _is_unavailable_model(status, code, detail):
                failures.append(f"{model}: HTTP {status} {code}".strip())
                continue
            raise OtariError(detail or f"HTTP {status}", status=status, code=code)
        raise FallbackExhausted(failures)

    def _payload(self, model: str, messages: list[dict[str, str]], max_tokens: int) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        if model == FALLBACK_MODEL:
            # Same cap under the newer field name, which wins when both are sent.
            payload["max_completion_tokens"] = max_tokens
        if self.user:
            payload["user"] = self.user
        if self.guardrails:
            payload["guardrails"] = self.guardrails
        if self.mcp_server_ids:
            payload["mcp_server_ids"] = list(self.mcp_server_ids)
        if self.mcp_servers:
            payload["mcp_servers"] = self.mcp_servers
        return payload

    def _trace(self, role: str, model: str, status: int, attempt: int, max_tokens: int, code: str = "") -> None:
        profiles = [str(item.get("profile", "")) for item in (self.guardrails or [])]
        modes = [str(item.get("mode", "")) for item in (self.guardrails or [])]
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
                guardrail_modes=modes,
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


def _tokens_for(model: str, requested: int) -> int:
    """Role calls stay clamped. gpt-oss gets a higher cap because it reasons first."""

    capped = clamp_max_tokens(requested)
    if model == FALLBACK_MODEL:
        return max(capped, FALLBACK_MAX_TOKENS)
    return capped


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


def _guardrail_signal(
    status: int,
    code: str,
    headers: dict[str, str],
    body: dict[str, Any],
) -> str | None:
    """Return ``block``, ``flag``, or None.

    A 403 ``guardrail_violation`` is the documented block. A 200 that carries
    a guardrail header or result marked flag/block is a flag. The request's
    own ``mode`` value is not scanned, so a normal completion is not a flag.
    A live flag body was not captured; the header and result-key checks are
    the handling path.
    """

    if status == 403 and (code == "guardrail_violation" or _header_says_guardrail(headers)):
        return "block"
    if _header_says_guardrail(headers):
        return "flag" if _header_is_flag(headers) else "block"
    for key in ("guardrail_results", "guardrails_result", "moderation"):
        found = _scan_guardrail_result(body.get(key))
        if found:
            return found
    return None


def _header_says_guardrail(headers: dict[str, str]) -> bool:
    for key, value in headers.items():
        if "guardrail" not in key:
            continue
        lowered = value.lower()
        if any(word in lowered for word in ("block", "flag", "violation")):
            return True
    return False


def _header_is_flag(headers: dict[str, str]) -> bool:
    blob = " ".join(value.lower() for key, value in headers.items() if "guardrail" in key)
    return "flag" in blob and "violation" not in blob and "block" not in blob


def _scan_guardrail_result(value: Any) -> str | None:
    if isinstance(value, dict):
        action = " ".join(
            str(value.get(key, "")) for key in ("action", "decision", "status", "outcome")
        ).lower()
        if "flag" in action:
            return "flag"
        if any(word in action for word in ("block", "violation")):
            return "block"
        return None
    if isinstance(value, list):
        for item in value:
            found = _scan_guardrail_result(item)
            if found:
                return found
    return None


def _is_unavailable_model(status: int, code: str, detail: str) -> bool:
    """A missing catalog id should fall through to the next model.

    404 is already retryable. Some gateways answer 400 or 422 instead.
    Auth and guardrail failures are classified earlier and are not this.
    """

    if status not in (400, 404, 422):
        return False
    blob = f"{code} {detail}".lower()
    if code.lower() in {"model_not_found", "unknown_model", "model_not_available", "model_unavailable"}:
        return True
    if "model" not in blob:
        return False
    return any(
        phrase in blob
        for phrase in (
            "not found",
            "does not exist",
            "doesn't exist",
            "unknown",
            "unavailable",
            "not available",
            "no such",
            "not supported",
        )
    )


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
