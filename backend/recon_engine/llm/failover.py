"""Provider failover orchestrator: Groq (primary) → Gemini → Cerebras →
OpenRouter (last resort, free models).

``FailoverLLMClient.complete_json`` is a drop-in for the old
``GroqJSONClient.complete_json`` — same messages in, same parsed JSON out — but
it attempts providers in order and fails over to the next one when a provider
raises a *retryable* error (rate limit / quota / token limit / timeout / service
unavailable / connection error, see :mod:`errors`). A non-retryable error
propagates instead of failing over, matching the spec (only the listed classes
trigger fallback).

Provider selection strategy (spec point 8)
------------------------------------------
A process-wide circuit breaker tracks the primary (Groq) only — the three
fallback tiers (Gemini, Cerebras, OpenRouter) are always tried in fixed order
on every request and carry no cooldown of their own. On a Groq retryable
failure the breaker trips for a cooldown window, during which Groq is *demoted*
below the fallbacks so requests go straight to Gemini instead of paying Groq's
latency + a wasted call on every request while it is rate-limited. Groq is never
fully excluded — if every fallback also fails it is still tried as a last resort.
A Groq success closes the breaker; after the cooldown expires Groq is promoted
back to first. This satisfies "switch away on failure, return to Groq once it
recovers" without hammering a limited Groq.

The provider actually used per request — and whether a fallback happened — is
recorded on a context variable (:func:`get_last_llm_outcome`) so routes can log
it and surface the non-blocking notification, without threading a return value
through the compiler/generator call chain.
"""

from __future__ import annotations

import contextvars
import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

from backend.recon_engine.compiler.base import ContractCompilerError
from backend.recon_engine.config import get_settings
from backend.recon_engine.llm.base import LLMProvider
from backend.recon_engine.llm.errors import AllProvidersUnavailableError, RetryableLLMError

logger = logging.getLogger("recon.llm.failover")

# User-facing notifications (spec points 5 and 6).
FALLBACK_NOTICE = (
    "Groq is temporarily unavailable or has reached its usage limit. "
    "Processing continued using OpenAI."
)
ALL_UNAVAILABLE_NOTICE = (
    "All configured AI providers are currently unavailable. Please try again later."
)

# Human-readable provider labels for the fallback notice.
_PROVIDER_LABELS = {
    "groq": "Groq",
    "gemini": "Gemini",
    "cerebras": "Cerebras",
    "openrouter": "OpenRouter",
    "openai": "OpenAI",
}


@dataclass(frozen=True)
class LLMOutcome:
    """Which provider served a request, and whether a fallback occurred."""

    preferred: str  # the primary provider we tried first (e.g. "groq")
    provider_used: str | None  # provider that actually served it, or None if all failed
    fallback_occurred: bool  # served by a non-preferred provider
    all_failed: bool  # every configured provider failed with a retryable error
    notice: str | None  # non-blocking message to surface, or None


# ── request-scoped outcome (read by the routes) ──────────────────────────────
_CURRENT_OUTCOME: contextvars.ContextVar[LLMOutcome | None] = contextvars.ContextVar(
    "recon_llm_outcome", default=None
)


def get_last_llm_outcome() -> LLMOutcome | None:
    """The outcome of the most recent ``complete_json`` in this context."""
    return _CURRENT_OUTCOME.get()


def reset_llm_outcome() -> None:
    """Clear the outcome (call at the start of a request)."""
    _CURRENT_OUTCOME.set(None)


def _record(outcome: LLMOutcome) -> None:
    _CURRENT_OUTCOME.set(outcome)


# ── circuit breaker (process-wide, shared across requests) ────────────────────
class CircuitBreaker:
    """A single open/closed gate with a time-based cooldown."""

    def __init__(self) -> None:
        self._open_until = 0.0
        self._lock = threading.Lock()

    def is_open(self, now: float) -> bool:
        with self._lock:
            return now < self._open_until

    def trip(self, now: float, cooldown_s: float) -> None:
        with self._lock:
            self._open_until = now + max(0.0, cooldown_s)

    def reset(self) -> None:
        with self._lock:
            self._open_until = 0.0


# Shared so the breaker state persists across requests (each request builds a
# fresh FailoverLLMClient, but they all consult the same primary breaker).
_PRIMARY_BREAKER = CircuitBreaker()


def reset_breaker() -> None:
    """Close the primary circuit breaker (used by tests)."""
    _PRIMARY_BREAKER.reset()


class FailoverLLMClient:
    """Try providers in order, failing over on retryable errors."""

    def __init__(
        self,
        providers: list[LLMProvider],
        *,
        cooldown_s: float = 60.0,
        breaker: CircuitBreaker | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not providers:
            raise ValueError("FailoverLLMClient requires at least one provider.")
        self._providers = providers
        self._cooldown_s = cooldown_s
        self._breaker = breaker if breaker is not None else _PRIMARY_BREAKER
        self._now = clock

    @property
    def preferred(self) -> str:
        return self._providers[0].name

    @property
    def is_configured(self) -> bool:
        return any(p.is_configured for p in self._providers)

    def _ordered(self, configured: list[LLMProvider]) -> list[LLMProvider]:
        """Provider order for this request, honouring the circuit breaker."""
        primary = self._providers[0]
        if primary in configured and self._breaker.is_open(self._now()):
            # Demote (don't exclude) the primary while its breaker is open.
            return [p for p in configured if p is not primary] + [primary]
        return configured

    def complete_json(self, messages: list[dict[str, str]]):
        configured = [p for p in self._providers if p.is_configured]
        if not configured:
            _record(
                LLMOutcome(
                    preferred=self.preferred,
                    provider_used=None,
                    fallback_occurred=False,
                    all_failed=False,
                    notice=None,
                )
            )
            raise ContractCompilerError(
                "No LLM provider is configured. Set GROQ_API_KEY and/or "
                "GEMINI_API_KEY/CEREBRAS_API_KEY/OPENROUTER_API_KEY."
            )

        for provider in self._ordered(configured):
            is_primary = provider.name == self.preferred
            try:
                payload = provider.complete_json(messages)
            except RetryableLLMError as exc:
                logger.warning(
                    "LLM provider %s failed with a retryable error; failing over. %s",
                    provider.name, exc,
                )
                if is_primary:
                    self._breaker.trip(self._now(), self._cooldown_s)
                continue
            except ContractCompilerError:
                # Non-retryable provider error — another provider is no more
                # likely to succeed, so do not fail over. Record and propagate.
                _record(
                    LLMOutcome(
                        preferred=self.preferred,
                        provider_used=provider.name,
                        fallback_occurred=not is_primary,
                        all_failed=False,
                        notice=self._fallback_notice(provider.name) if not is_primary else None,
                    )
                )
                raise
            else:
                if is_primary:
                    self._breaker.reset()
                fallback = not is_primary
                logger.info(
                    "LLM request served by provider=%s (preferred=%s, fallback=%s)",
                    provider.name, self.preferred, fallback,
                )
                _record(
                    LLMOutcome(
                        preferred=self.preferred,
                        provider_used=provider.name,
                        fallback_occurred=fallback,
                        all_failed=False,
                        notice=self._fallback_notice(provider.name) if fallback else None,
                    )
                )
                return payload

        # Every configured provider raised a retryable error.
        logger.error("All configured LLM providers are unavailable (retryable failures).")
        _record(
            LLMOutcome(
                preferred=self.preferred,
                provider_used=None,
                fallback_occurred=False,
                all_failed=True,
                notice=ALL_UNAVAILABLE_NOTICE,
            )
        )
        raise AllProvidersUnavailableError(ALL_UNAVAILABLE_NOTICE)

    @staticmethod
    def _fallback_notice(provider_name: str) -> str:
        label = _PROVIDER_LABELS.get(provider_name, provider_name)
        if provider_name == "openai":
            return FALLBACK_NOTICE
        return (
            "Groq is temporarily unavailable or has reached its usage limit. "
            f"Processing continued using {label}."
        )


def build_llm_client(
    *, groq_api_key: str | None = None, groq_model: str | None = None
) -> FailoverLLMClient:
    """Construct the Groq→Gemini→Cerebras→OpenRouter failover client from settings.

    Groq is the primary; Gemini, Cerebras, then OpenRouter (free models) are
    tried in order as it fails over. ``groq_api_key`` / ``groq_model`` override
    the primary's credentials (used by callers/tests that inject them). Each
    fallback tier reads its own key/model from settings — a tier with no key
    configured is simply skipped (see ``FailoverLLMClient.complete_json``).
    """
    # Imported lazily to avoid an import cycle: groq_client imports llm.errors.
    from backend.recon_engine.compiler.groq_client import GroqJSONClient
    from backend.recon_engine.llm.cerebras_client import CerebrasJSONClient
    from backend.recon_engine.llm.gemini_client import GeminiJSONClient
    from backend.recon_engine.llm.openrouter_client import OpenRouterJSONClient

    settings = get_settings()
    providers: list[LLMProvider] = [
        GroqJSONClient(api_key=groq_api_key, model=groq_model),
        GeminiJSONClient(),
        CerebrasJSONClient(),
        OpenRouterJSONClient(),
    ]
    return FailoverLLMClient(providers, cooldown_s=settings.llm_fallback_cooldown_s)
