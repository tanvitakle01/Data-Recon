"""LLM failover error types and retryable-failure classification.

The failover orchestrator (:mod:`backend.recon_engine.llm.failover`) only moves
on to the next provider when a provider fails with a *retryable* error — the
availability/capacity class the spec calls out: rate limit (429), quota/token
exhaustion, timeout, service unavailable (5xx), or a connection error. Anything
else (a malformed response, a schema violation, a bad request) is a genuine
error that another provider is no more likely to get right, so it propagates.

Classification is deliberately duck-typed by exception *class name*, HTTP status
and message text rather than by importing ``groq``/``openai`` exception classes.
Both SDKs are optional dependencies and use parallel hierarchies
(``RateLimitError``, ``APITimeoutError``, ``APIConnectionError``,
``InternalServerError``, ...); matching on shape keeps this module import-light
and provider-agnostic.
"""

from __future__ import annotations

from typing import Any

from backend.recon_engine.compiler.base import ContractCompilerError


class RetryableLLMError(ContractCompilerError):
    """A provider failure that is safe to retry on another provider.

    Subclasses :class:`ContractCompilerError` so that if one ever escapes the
    failover orchestrator, every existing ``except ContractCompilerError``
    handler still degrades gracefully instead of surfacing a 500.
    """

    def __init__(self, message: str, *, provider: str) -> None:
        super().__init__(message)
        self.provider = provider


class AllProvidersUnavailableError(ContractCompilerError):
    """Every configured LLM provider failed with a retryable error."""


# HTTP statuses that indicate a transient/capacity failure worth failing over on.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# Substrings that identify a retryable failure in an exception message. Covers
# rate limits, quota/token exhaustion, timeouts, unavailability and connection
# faults across both providers' error text.
_RETRYABLE_MARKERS = (
    "rate limit",
    "ratelimit",
    "rate_limit",
    "too many requests",
    "quota",
    "insufficient_quota",
    "token limit",
    "tokens per",
    "requests per",
    "context length",
    "maximum context",
    "timeout",
    "timed out",
    "temporarily unavailable",
    "service unavailable",
    "overloaded",
    "connection error",
    "connection aborted",
    "connection reset",
    "connection refused",
    "econnreset",
    "429",
    "503",
)

# Exception class-name fragments that mark a retryable failure regardless of
# which SDK raised them.
_RETRYABLE_NAME_FRAGMENTS = (
    "ratelimit",
    "timeout",
    "apiconnection",
    "connectionerror",
    "serviceunavailable",
    "internalservererror",
    "apitimeout",
    "overloaded",
)


def _status_of(exc: Any) -> int | None:
    for attr in ("status_code", "http_status", "status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    if response is not None:
        value = getattr(response, "status_code", None)
        if isinstance(value, int):
            return value
    return None


def is_retryable_exception(exc: BaseException) -> bool:
    """True when ``exc`` is a rate-limit/quota/timeout/unavailable/connection
    failure that should trigger failover to the next provider."""
    name = type(exc).__name__.lower()
    if any(fragment in name for fragment in _RETRYABLE_NAME_FRAGMENTS):
        return True
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    if _status_of(exc) in _RETRYABLE_STATUS:
        return True
    message = str(exc).lower()
    return any(marker in message for marker in _RETRYABLE_MARKERS)
