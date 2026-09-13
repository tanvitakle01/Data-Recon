"""LLM failover: classification, orchestration, circuit breaker, provider
provenance (generic ``FailoverLLMClient`` behaviour, exercised with fake
providers — reusable infrastructure only), plus end-to-end coverage that
``build_llm_client()`` — and therefore the compile path — is
Azure-AI-Foundry-only, the sole LLM provider in this codebase. No live API
calls (providers are faked and the OpenAI SDK, which Azure Foundry reuses via
base_url, is monkeypatched).
"""

from __future__ import annotations

import pytest

from backend.recon_engine import service
from backend.recon_engine.compiler.base import ContractCompilerError
from backend.recon_engine.config import reset_settings_cache
from backend.recon_engine.llm import (
    ALL_UNAVAILABLE_NOTICE,
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


# ── orchestration (generic FailoverLLMClient, exercised with fake providers —
#    reusable infrastructure only; Azure AI Foundry is the only real provider) ──

def test_failover_to_secondary_on_retryable_primary_error():
    primary = _FakeProvider("primary", behavior=_raise(RetryableLLMError("429", provider="primary")))
    secondary = _FakeProvider("secondary", behavior=_ok({"ok": True}))
    client = FailoverLLMClient([primary, secondary], breaker=CircuitBreaker(), clock=_Clock())

    assert client.complete_json([]) == {"ok": True}
    assert primary.calls == 1 and secondary.calls == 1

    outcome = get_last_llm_outcome()
    assert outcome.provider_used == "secondary"
    assert outcome.fallback_occurred is True
    assert outcome.notice is not None and "secondary" in outcome.notice


def test_primary_success_no_fallback():
    primary = _FakeProvider("primary", behavior=_ok({"ok": 1}))
    secondary = _FakeProvider("secondary", behavior=_ok({"ok": 2}))
    client = FailoverLLMClient([primary, secondary], breaker=CircuitBreaker(), clock=_Clock())

    assert client.complete_json([]) == {"ok": 1}
    assert secondary.calls == 0
    outcome = get_last_llm_outcome()
    assert outcome.provider_used == "primary"
    assert outcome.fallback_occurred is False
    assert outcome.notice is None


def test_non_retryable_error_does_not_fail_over():
    """Only the listed availability errors trigger failover; a genuine error
    (e.g. malformed response) propagates without calling the next provider."""
    primary = _FakeProvider("primary", behavior=_raise(ContractCompilerError("bad JSON")))
    secondary = _FakeProvider("secondary", behavior=_ok({"ok": True}))
    client = FailoverLLMClient([primary, secondary], breaker=CircuitBreaker(), clock=_Clock())

    with pytest.raises(ContractCompilerError):
        client.complete_json([])
    assert secondary.calls == 0


def test_all_providers_unavailable_raises_clear_error():
    primary = _FakeProvider("primary", behavior=_raise(RetryableLLMError("429", provider="primary")))
    secondary = _FakeProvider("secondary", behavior=_raise(RetryableLLMError("429", provider="secondary")))
    client = FailoverLLMClient([primary, secondary], breaker=CircuitBreaker(), clock=_Clock())

    with pytest.raises(AllProvidersUnavailableError) as ei:
        client.complete_json([])
    assert str(ei.value) == ALL_UNAVAILABLE_NOTICE
    outcome = get_last_llm_outcome()
    assert outcome.all_failed is True
    assert outcome.notice == ALL_UNAVAILABLE_NOTICE


def test_no_provider_configured_raises():
    primary = _FakeProvider("primary", configured=False, behavior=_ok({}))
    secondary = _FakeProvider("secondary", configured=False, behavior=_ok({}))
    client = FailoverLLMClient([primary, secondary], breaker=CircuitBreaker(), clock=_Clock())
    with pytest.raises(ContractCompilerError):
        client.complete_json([])


# ── circuit breaker (spec point 8) ───────────────────────────────────────────

def test_circuit_breaker_demotes_then_returns_to_primary():
    clock = _Clock()
    breaker = CircuitBreaker()
    calls = {"primary": 0, "secondary": 0}

    primary = _FakeProvider("primary")
    secondary = _FakeProvider("secondary")

    def primary_behavior(_m):
        calls["primary"] += 1
        # Primary is rate-limited until t >= 60, then healthy again.
        if clock.t < 60:
            raise RetryableLLMError("429", provider="primary")
        return {"by": "primary"}

    def secondary_behavior(_m):
        calls["secondary"] += 1
        return {"by": "secondary"}

    primary._behavior = primary_behavior
    secondary._behavior = secondary_behavior
    client = FailoverLLMClient([primary, secondary], cooldown_s=60, breaker=breaker, clock=clock)

    # req1 (t=0): primary 429 → trips breaker → secondary serves.
    assert client.complete_json([])["by"] == "secondary"
    assert calls == {"primary": 1, "secondary": 1}

    # req2 (t=10, breaker open): primary demoted → secondary first, primary never tried.
    clock.t = 10
    assert client.complete_json([])["by"] == "secondary"
    assert calls == {"primary": 1, "secondary": 2}  # primary not re-called

    # req3 (t=70, cooldown elapsed): primary promoted back and now healthy.
    clock.t = 70
    assert client.complete_json([])["by"] == "primary"
    assert calls == {"primary": 2, "secondary": 2}
    assert breaker.is_open(clock.t) is False  # a primary success closed it


# ── end-to-end: build_llm_client() is Azure-AI-Foundry-only, no fallback ────

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


def test_compile_draft_uses_azure_foundry_with_no_fallback(monkeypatch):
    """Azure AI Foundry alone serves the request — there is no other provider
    to fail over to, and no fallback/failover notice."""
    monkeypatch.setenv("AZURE_FOUNDRY_MODEL", "DeepSeek-V4-Pro")
    monkeypatch.setenv("AZURE_FOUNDRY_BASE_URL", "https://fake.example.com/openai/v1")
    reset_settings_cache()

    from backend.recon_engine.llm.azure_foundry_client import AzureFoundryJSONClient

    monkeypatch.setattr(AzureFoundryJSONClient, "complete_json", lambda self, messages: dict(_VALID_CONTRACT))

    draft, degraded_reason = service.compile_draft(
        mapping_sheet=_MAPPING, rules="", source_schema=["id", "qty"],
        target_schema=["id", "qty"], comparison_type="sales_history",
        source_type="s4", target_type="ibp",
    )
    assert draft.compiler == "azure_foundry"
    assert degraded_reason is None
    outcome = get_last_llm_outcome()
    assert outcome.fallback_occurred is False
    assert outcome.provider_used == "azure_foundry"


def test_compile_draft_degrades_to_stub_when_azure_foundry_unavailable(monkeypatch):
    """A retryable Azure AI Foundry failure has nothing to fail over to — it
    degrades straight to the deterministic stub compiler (default, non-strict
    mode)."""
    monkeypatch.setenv("AZURE_FOUNDRY_MODEL", "DeepSeek-V4-Pro")
    monkeypatch.setenv("AZURE_FOUNDRY_BASE_URL", "https://fake.example.com/openai/v1")
    reset_settings_cache()

    from backend.recon_engine.llm.azure_foundry_client import AzureFoundryJSONClient

    def _azure_foundry_503(self, messages):
        raise RetryableLLMError("Azure AI Foundry API call failed: 503", provider="azure_foundry")

    monkeypatch.setattr(AzureFoundryJSONClient, "complete_json", _azure_foundry_503)

    draft, degraded_reason = service.compile_draft(
        mapping_sheet=_MAPPING, rules="", source_schema=["id", "qty"],
        target_schema=["id", "qty"], comparison_type="sales_history",
        source_type="s4", target_type="ibp",
    )
    assert draft.compiler == "stub"
    assert degraded_reason is not None
    outcome = get_last_llm_outcome()
    assert outcome.all_failed is True
    assert outcome.provider_used is None


def test_azure_foundry_client_uses_openai_compatible_sdk(monkeypatch):
    """AzureFoundryJSONClient reuses the openai SDK against the Azure AI
    Foundry base_url, authenticating via an Azure AD bearer-token callable
    rather than a static API key."""
    monkeypatch.setenv("AZURE_FOUNDRY_MODEL", "DeepSeek-V4-Pro")
    monkeypatch.setenv("AZURE_FOUNDRY_BASE_URL", "https://fake.example.com/openai/v1")
    reset_settings_cache()

    class _Msg:
        content = '{"hello": "azure_foundry"}'

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

    class _Completions:
        def create(self, **kwargs):
            assert kwargs["model"] == "DeepSeek-V4-Pro"
            return _Resp()

    class _Chat:
        completions = _Completions()

    class _FakeOpenAI:
        def __init__(self, **kwargs):
            assert kwargs["base_url"] == "https://fake.example.com/openai/v1"
            assert callable(kwargs["api_key"])
            self.chat = _Chat()

    import openai
    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)

    from backend.recon_engine.llm.azure_foundry_client import AzureFoundryJSONClient
    client = AzureFoundryJSONClient()
    assert client.is_configured is True
    assert client.complete_json([{"role": "user", "content": "hi"}]) == {"hello": "azure_foundry"}


def test_azure_foundry_client_without_a_model_fails_loudly(monkeypatch):
    """A client built without a model id must not silently guess one — it
    should raise a clear, actionable error instead of a confusing API error."""
    reset_settings_cache()

    from backend.recon_engine.llm.azure_foundry_client import AzureFoundryJSONClient
    client = AzureFoundryJSONClient(api_key="static-fake-key-for-this-test")
    assert client.is_configured is False  # no AZURE_FOUNDRY_MODEL set
    with pytest.raises(ContractCompilerError, match="AZURE_FOUNDRY_MODEL"):
        client.complete_json([{"role": "user", "content": "hi"}])


def test_compile_route_surfaces_provider_fields(monkeypatch):
    """The /compile HTTP response carries provider/fallback/provider_notice so
    the frontend can show the non-blocking notice (contextvar → route). With
    Azure AI Foundry as the sole provider, a successful compile is never a
    fallback."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.recon_engine.llm.azure_foundry_client import AzureFoundryJSONClient
    from backend.routes.contracts import router

    monkeypatch.setenv("AZURE_FOUNDRY_MODEL", "DeepSeek-V4-Pro")
    monkeypatch.setenv("AZURE_FOUNDRY_BASE_URL", "https://fake.example.com/openai/v1")
    reset_settings_cache()
    monkeypatch.setattr(AzureFoundryJSONClient, "complete_json", lambda self, messages: dict(_VALID_CONTRACT))

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
    assert body["provider"] == "azure_foundry"
    assert body["fallback"] is False
    assert body["provider_notice"] is None
    assert body["degraded"] is False
