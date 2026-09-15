"""LLM client construction: ``build_llm_client()`` returns an
Azure-AI-Foundry-only client — Azure AI Foundry is the ONLY LLM provider in
this codebase; no other provider client exists to fail over to.

``FailoverLLMClient`` is a generic multi-provider orchestrator kept as
reusable infrastructure (tests exercise it with fake providers), but
``build_llm_client()`` constructs it with only a single
``AzureFoundryJSONClient``, so there is nothing to fail over to in
production — an Azure AI Foundry failure propagates (or is classified
retryable and raises :class:`AllProvidersUnavailableError`) rather than
trying another provider.

``FailoverLLMClient.complete_json`` takes messages in, returns parsed JSON
out. When given more than one provider it attempts them in order and fails
over to the next one on a *retryable* error (rate limit / quota / token limit
/ timeout / service unavailable / connection error, see :mod:`errors`); a
non-retryable error propagates instead of failing over.

The provider actually used per request is recorded on a context variable
(:func:`get_last_llm_outcome`) so routes can log it, without threading a return
value through the compiler/generator call chain.
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
from backend.recon_engine.llm.call_context import get_llm_call_context
from backend.recon_engine.llm.errors import AllProvidersUnavailableError, RetryableLLMError
from backend.recon_engine.storage import llm_call_store

logger = logging.getLogger("recon.llm.failover")

# User-facing notifications. Dead in production (Azure AI Foundry is the only
# configured provider, so there is nothing to fail over to), kept for the
# generic FailoverLLMClient's fake-provider test coverage.
FALLBACK_NOTICE = "The primary AI provider is temporarily unavailable. Processing continued using a fallback provider."
ALL_UNAVAILABLE_NOTICE = (
    "All configured AI providers are currently unavailable. Please try again later."
)

# Human-readable provider labels for the fallback notice.
_PROVIDER_LABELS = {
    "azure_foundry": "Azure AI Foundry",
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
    ctx = get_llm_call_context()
    llm_call_store.record(
        run_id=ctx.run_id,
        batch_id=ctx.batch_id,
        node=ctx.node,
        preferred=outcome.preferred,
        provider_used=outcome.provider_used,
        fallback_occurred=outcome.fallback_occurred,
        all_failed=outcome.all_failed,
    )


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
                "No LLM provider is configured. Set AZURE_FOUNDRY_MODEL "
                "(and sign in to Azure AD, e.g. `az login`, for DefaultAzureCredential)."
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
        return f"The primary AI provider is temporarily unavailable. Processing continued using {label}."


def build_llm_client(
    *, api_key: str | None = None, model: str | None = None
) -> FailoverLLMClient:
    """Construct the Azure-AI-Foundry-only LLM client used by every call site
    in the engine (contract compiler, field mapper, sheet identifier, chat
    assistant, value pairing, script generator).

    **This is the single endpoint-resolution point.** Every LLM call path —
    mapping-sheet classification, header binding, value pairing, script
    generation — goes through here, and they all reach the same endpoint: the
    app's own Azure AI Foundry deployment. There is no per-user or per-session
    credential anywhere in the app; a request cannot redirect an LLM call.

    Azure AI Foundry is the sole provider — there is no failover to Groq,
    Cerebras, OpenRouter, or OpenAI. ``model`` overrides the configured model
    id (used by callers/tests that inject it); otherwise it is read from
    settings (``AZURE_FOUNDRY_MODEL``). ``api_key`` overrides the Azure AD
    token provider with a static value (used by tests only — production auth
    is always via ``DefaultAzureCredential``).
    """
    from backend.recon_engine.llm.azure_foundry_client import AzureFoundryJSONClient

    settings = get_settings()

    # The line that answers "which endpoint served this run?". Endpoint and
    # model only — the credential itself is never logged, in any environment.
    logger.info(
        "LLM endpoint base_url=%s model=%s",
        settings.azure_foundry.base_url or "unset",
        model or settings.azure_foundry.model or "unset",
    )

    providers: list[LLMProvider] = [AzureFoundryJSONClient(api_key=api_key, model=model)]
    return FailoverLLMClient(providers, cooldown_s=settings.llm_fallback_cooldown_s)
