"""Automatic Groq→Gemini→Cerebras→OpenRouter LLM failover: classification,
orchestration, circuit breaker, provider provenance, and the end-to-end
compile path.

These prove that a Groq rate-limit/quota/timeout/outage transparently continues
on the next configured tier — deterministically, with no live API calls
(providers are faked and the OpenAI SDK, which Gemini/Cerebras/OpenRouter all
reuse via base_url, is monkeypatched).
"""

from __future__ import annotations

import pytest

from backend.recon_engine import service
from backend.recon_engine.compiler.base import ContractCompilerError
from backend.recon_engine.config import reset_settings_cache
from backend.recon_engine.llm import (
    ALL_UNAVAILABLE_NOTICE,
    FALLBACK_NOTICE,
    AllProvidersUnavailableError,
    RetryableLLMError,
    get_last_llm_outcome,
    is_retryable_exception,
)
from backend.recon_engine.llm.failover import CircuitBreaker, FailoverLLMClient


# ── fakes ────────────────────────────────────────────────────────────────────

class _FakeProvider:
    def __init__(self, name, *, configured=True, behavior=None):
        self.name = name
        self._configured = configured
        self._behavior = behavior  # callable(messages) -> payload, or raises
        self.calls = 0

    @property
    def is_configured(self):
        return self._configured

    def complete_json(self, messages):
        self.calls += 1
        return self._behavior(messages)


def _ok(payload):
    return lambda _messages: payload


def _raise(exc):
    def _behavior(_messages):
        raise exc
    return _behavior


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


# ── retryable classification (spec point 2) ──────────────────────────────────

@pytest.mark.parametrize(
    "exc, expected",
    [
        (type("RateLimitError", (Exception,), {})("boom"), True),
        (type("APITimeoutError", (Exception,), {})("boom"), True),
        (type("APIConnectionError", (Exception,), {})("boom"), True),
        (type("InternalServerError", (Exception,), {})("boom"), True),
        (TimeoutError("timed out"), True),
        (ConnectionError("connection reset"), True),
        (Exception("Error code: 429 - rate_limit_exceeded"), True),
        (Exception("tokens per day (TPD): Limit 100000"), True),
        (Exception("insufficient_quota"), True),
        (Exception("service unavailable (503)"), True),
        (Exception("invalid api key"), False),
        (Exception("response was not valid JSON"), False),
        (ValueError("bad request 400"), False),
    ],
)
def test_is_retryable_exception(exc, expected):
    assert is_retryable_exception(exc) is expected


def test_status_code_attribute_is_retryable():
    exc = type("APIStatusError", (Exception,), {})("x")
    exc.status_code = 503
    assert is_retryable_exception(exc) is True
    exc.status_code = 400
    # class name isn't a known-retryable fragment and 400 isn't retryable
    assert is_retryable_exception(exc) is False


# ── orchestration ────────────────────────────────────────────────────────────

def test_failover_to_openai_on_retryable_groq_error():
    groq = _FakeProvider("groq", behavior=_raise(RetryableLLMError("429", provider="groq")))
    openai = _FakeProvider("openai", behavior=_ok({"ok": True}))
    client = FailoverLLMClient([groq, openai], breaker=CircuitBreaker(), clock=_Clock())

    assert client.complete_json([]) == {"ok": True}
    assert groq.calls == 1 and openai.calls == 1

    outcome = get_last_llm_outcome()
    assert outcome.provider_used == "openai"
    assert outcome.fallback_occurred is True
    assert outcome.notice == FALLBACK_NOTICE


def test_primary_success_no_fallback():
    groq = _FakeProvider("groq", behavior=_ok({"ok": 1}))
    openai = _FakeProvider("openai", behavior=_ok({"ok": 2}))
    client = FailoverLLMClient([groq, openai], breaker=CircuitBreaker(), clock=_Clock())

    assert client.complete_json([]) == {"ok": 1}
    assert openai.calls == 0
    outcome = get_last_llm_outcome()
    assert outcome.provider_used == "groq"
    assert outcome.fallback_occurred is False
    assert outcome.notice is None


def test_non_retryable_error_does_not_fail_over():
    """Only the listed availability errors trigger failover; a genuine error
    (e.g. malformed response) propagates without calling the next provider."""
    groq = _FakeProvider("groq", behavior=_raise(ContractCompilerError("bad JSON")))
    openai = _FakeProvider("openai", behavior=_ok({"ok": True}))
    client = FailoverLLMClient([groq, openai], breaker=CircuitBreaker(), clock=_Clock())

    with pytest.raises(ContractCompilerError):
        client.complete_json([])
    assert openai.calls == 0


def test_all_providers_unavailable_raises_clear_error():
    groq = _FakeProvider("groq", behavior=_raise(RetryableLLMError("429", provider="groq")))
    openai = _FakeProvider("openai", behavior=_raise(RetryableLLMError("429", provider="openai")))
    client = FailoverLLMClient([groq, openai], breaker=CircuitBreaker(), clock=_Clock())

    with pytest.raises(AllProvidersUnavailableError) as ei:
        client.complete_json([])
    assert str(ei.value) == ALL_UNAVAILABLE_NOTICE
    outcome = get_last_llm_outcome()
    assert outcome.all_failed is True
    assert outcome.notice == ALL_UNAVAILABLE_NOTICE


def test_no_provider_configured_raises():
    groq = _FakeProvider("groq", configured=False, behavior=_ok({}))
    openai = _FakeProvider("openai", configured=False, behavior=_ok({}))
    client = FailoverLLMClient([groq, openai], breaker=CircuitBreaker(), clock=_Clock())
    with pytest.raises(ContractCompilerError):
        client.complete_json([])


# ── circuit breaker (spec point 8) ───────────────────────────────────────────

def test_circuit_breaker_demotes_then_returns_to_groq():
    clock = _Clock()
    breaker = CircuitBreaker()
    calls = {"groq": 0, "openai": 0}

    groq = _FakeProvider("groq")
    openai = _FakeProvider("openai")

    def groq_behavior(_m):
        calls["groq"] += 1
        # Groq is rate-limited until t >= 60, then healthy again.
        if clock.t < 60:
            raise RetryableLLMError("429", provider="groq")
        return {"by": "groq"}

    def openai_behavior(_m):
        calls["openai"] += 1
        return {"by": "openai"}

    groq._behavior = groq_behavior
    openai._behavior = openai_behavior
    client = FailoverLLMClient([groq, openai], cooldown_s=60, breaker=breaker, clock=clock)

    # req1 (t=0): Groq 429 → trips breaker → OpenAI serves.
    assert client.complete_json([])["by"] == "openai"
    assert calls == {"groq": 1, "openai": 1}

    # req2 (t=10, breaker open): Groq demoted → OpenAI first, Groq never tried.
    clock.t = 10
    assert client.complete_json([])["by"] == "openai"
    assert calls == {"groq": 1, "openai": 2}  # groq not re-called

    # req3 (t=70, cooldown elapsed): Groq promoted back and now healthy.
    clock.t = 70
    assert client.complete_json([])["by"] == "groq"
    assert calls == {"groq": 2, "openai": 2}
    assert breaker.is_open(clock.t) is False  # a Groq success closed it


# ── end-to-end through compile_draft + the OpenAI client ─────────────────────

_VALID_CONTRACT = {
    "comparison_type": "sales_history",
    "source_type": "s4",
    "target_type": "ibp",
    "operations": [],
    "business_key": [{"source_field": "id", "target_field": "id"}],
    "compare_fields": [{"source_field": "qty", "target_field": "qty"}],
    "source_schema": ["id", "qty"],
    "target_schema": ["id", "qty"],
}

_MAPPING = [
    {"source_col": "id", "target_col": "id", "role": "key"},
    {"source_col": "qty", "target_col": "qty", "role": "compare"},
]


def test_compile_draft_fails_over_to_gemini(monkeypatch):
    """With both keys set, a Groq retryable failure produces a Gemini-authored
    draft (compiler=='gemini', tier 2), no degradation, and a fallback notice."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk_fake")
    monkeypatch.setenv("GEMINI_API_KEY", "gm_fake")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.0-flash")
    reset_settings_cache()

    from backend.recon_engine.compiler.groq_client import GroqJSONClient
    from backend.recon_engine.llm.gemini_client import GeminiJSONClient

    def _groq_429(self, messages):
        raise RetryableLLMError("Groq API call failed: 429 rate_limit_exceeded", provider="groq")

    monkeypatch.setattr(GroqJSONClient, "complete_json", _groq_429)
    monkeypatch.setattr(GeminiJSONClient, "complete_json", lambda self, messages: dict(_VALID_CONTRACT))

    draft, degraded_reason = service.compile_draft(
        mapping_sheet=_MAPPING, rules="", source_schema=["id", "qty"],
        target_schema=["id", "qty"], comparison_type="sales_history",
        source_type="s4", target_type="ibp",
    )
    assert draft.compiler == "gemini"       # provenance = actual provider
    assert degraded_reason is None          # Gemini succeeded → no degradation
    outcome = get_last_llm_outcome()
    assert outcome.fallback_occurred is True
    assert outcome.provider_used == "gemini"


def test_compile_draft_falls_through_all_four_tiers_in_order(monkeypatch):
    """Groq, Gemini, and Cerebras all fail with a retryable error; OpenRouter
    (the last resort, free-model tier) serves the request."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk_fake")
    monkeypatch.setenv("GEMINI_API_KEY", "gm_fake")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.0-flash")
    monkeypatch.setenv("CEREBRAS_API_KEY", "cb_fake")
    monkeypatch.setenv("CEREBRAS_MODEL", "llama3.1-8b")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or_fake")
    reset_settings_cache()

    from backend.recon_engine.compiler.groq_client import GroqJSONClient
    from backend.recon_engine.llm.cerebras_client import CerebrasJSONClient
    from backend.recon_engine.llm.gemini_client import GeminiJSONClient
    from backend.recon_engine.llm.openrouter_client import OpenRouterJSONClient

    def _retryable(name):
        def _behavior(self, messages):
            raise RetryableLLMError(f"{name} API call failed: 503", provider=name)
        return _behavior

    monkeypatch.setattr(GroqJSONClient, "complete_json", _retryable("groq"))
    monkeypatch.setattr(GeminiJSONClient, "complete_json", _retryable("gemini"))
    monkeypatch.setattr(CerebrasJSONClient, "complete_json", _retryable("cerebras"))
    monkeypatch.setattr(OpenRouterJSONClient, "complete_json", lambda self, messages: dict(_VALID_CONTRACT))

    draft, degraded_reason = service.compile_draft(
        mapping_sheet=_MAPPING, rules="", source_schema=["id", "qty"],
        target_schema=["id", "qty"], comparison_type="sales_history",
        source_type="s4", target_type="ibp",
    )
    assert draft.compiler == "openrouter"
    assert degraded_reason is None
    outcome = get_last_llm_outcome()
    assert outcome.fallback_occurred is True
    assert outcome.provider_used == "openrouter"


def test_openai_client_uses_sdk(monkeypatch):
    """The real OpenAIJSONClient parses a chat-completion JSON response."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk_fake")
    reset_settings_cache()

    class _Msg:
        content = '{"hello": "world"}'

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

    class _Completions:
        def create(self, **kwargs):
            assert kwargs["temperature"] == 0
            return _Resp()

    class _Chat:
        completions = _Completions()

    class _FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = _Chat()

    import openai
    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)

    from backend.recon_engine.llm.openai_client import OpenAIJSONClient
    client = OpenAIJSONClient()
    assert client.is_configured is True
    assert client.complete_json([{"role": "user", "content": "hi"}]) == {"hello": "world"}


def test_gemini_client_uses_openai_compatible_sdk(monkeypatch):
    """GeminiJSONClient reuses the openai SDK against Gemini's base_url."""
    monkeypatch.setenv("GEMINI_API_KEY", "gm_fake")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.0-flash")
    reset_settings_cache()

    class _Msg:
        content = '{"hello": "gemini"}'

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

    class _Completions:
        def create(self, **kwargs):
            assert kwargs["model"] == "gemini-2.0-flash"
            return _Resp()

    class _Chat:
        completions = _Completions()

    class _FakeOpenAI:
        def __init__(self, **kwargs):
            assert kwargs["base_url"] == "https://generativelanguage.googleapis.com/v1beta/openai/"
            self.chat = _Chat()

    import openai
    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)

    from backend.recon_engine.llm.gemini_client import GeminiJSONClient
    client = GeminiJSONClient()
    assert client.is_configured is True
    assert client.complete_json([{"role": "user", "content": "hi"}]) == {"hello": "gemini"}


def test_fallback_tier_without_a_model_env_var_fails_loudly(monkeypatch):
    """A configured API key but no model id must not silently guess a model —
    it should raise a clear, actionable error instead."""
    monkeypatch.setenv("CEREBRAS_API_KEY", "cb_fake")
    monkeypatch.delenv("CEREBRAS_MODEL", raising=False)
    reset_settings_cache()

    from backend.recon_engine.llm.cerebras_client import CerebrasJSONClient
    client = CerebrasJSONClient()
    assert client.is_configured is True  # a key alone is enough for is_configured
    with pytest.raises(ContractCompilerError, match="CEREBRAS_MODEL"):
        client.complete_json([{"role": "user", "content": "hi"}])


def test_compile_route_surfaces_fallback_fields(monkeypatch):
    """The /compile HTTP response carries provider/fallback/provider_notice so
    the frontend can show the non-blocking notice (contextvar → route)."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.recon_engine.compiler.groq_client import GroqJSONClient
    from backend.recon_engine.llm.gemini_client import GeminiJSONClient
    from backend.routes.contracts import router

    monkeypatch.setenv("GROQ_API_KEY", "gsk_fake")
    monkeypatch.setenv("GEMINI_API_KEY", "gm_fake")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.0-flash")
    reset_settings_cache()
    monkeypatch.setattr(
        GroqJSONClient, "complete_json",
        lambda self, messages: (_ for _ in ()).throw(
            RetryableLLMError("429 rate_limit_exceeded", provider="groq")
        ),
    )
    monkeypatch.setattr(GeminiJSONClient, "complete_json", lambda self, messages: dict(_VALID_CONTRACT))

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    resp = client.post(
        "/api/recon/contracts/compile",
        json={
            "mapping_sheet": _MAPPING,
            "source_schema": ["id", "qty"],
            "target_schema": ["id", "qty"],
            "comparison_type": "sales_history",
            "source_type": "s4",
            "target_type": "ibp",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provider"] == "gemini"
    assert body["fallback"] is True
    assert body["provider_notice"] is not None
    assert body["degraded"] is False
