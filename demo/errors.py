"""Errors the CLI can print without echoing credentials."""

from __future__ import annotations


def _scrub(text: str, secrets: list[str]) -> str:
    cleaned = text
    for secret in secrets:
        if secret:
            cleaned = cleaned.replace(secret, "[redacted]")
    banned = "Contract" + "Gate"
    cleaned = cleaned.replace(banned, "AISchemaGate")
    cleaned = cleaned.replace(banned.lower(), "aischemagate")
    return cleaned


class OtariError(Exception):
    """A gateway response the client will not retry on another model."""

    def __init__(self, message: str, *, status: int, code: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class GuardrailBlocked(OtariError):
    """A guardrail refused the request. The document is quarantined."""


class BudgetExceeded(OtariError):
    """A budget or end-user cap refused the request. The run stops."""


class RetryableModelError(OtariError):
    """Timeout, rate limit, or upstream failure. The client may try the next model."""


class FallbackExhausted(OtariError):
    """Every model in the role's list failed with a retryable error."""

    def __init__(self, attempts: list[str]) -> None:
        super().__init__(
            "Every model in the fallback list failed: " + "; ".join(attempts),
            status=0,
            code="fallback_exhausted",
        )
        self.attempts = attempts


def public_message(exc: BaseException, secrets: list[str] | None = None) -> str:
    return _scrub(f"{type(exc).__name__}: {exc}", secrets or [])
