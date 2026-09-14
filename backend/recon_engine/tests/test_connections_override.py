"""Connections tab — session-scoped LLM endpoint override.

Covers the feature's acceptance criteria end to end against the REAL app
(``backend.main.app``), so the middleware that binds a request's override is
exercised rather than a stand-in:

* an invalid key fails the test and is not stored;
* a saved override is what ``build_llm_client()`` — the single
  endpoint-resolution point — actually resolves, for every LLM call site;
* the endpoint source is named in a log line, and the key never is;
* dropping the token (what a page refresh does) reverts to the default.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from backend import main as main_module
from backend.recon_engine.compiler.base import ContractCompilerError
from backend.recon_engine.config import reset_settings_cache
from backend.recon_engine.llm import build_llm_client, session_override
from backend.recon_engine.llm.azure_foundry_client import AzureFoundryJSONClient
from backend.routes import connections as connections_route

GOOD_KEY = "sk-live-abcdefghijklmnop-7f3c"
BAD_KEY = "sk-live-not-a-real-key-0000"
DEFAULT_BASE = "https://app-default.services.ai.azure.com/openai/v1"
CUSTOM_BASE = "https://my-own-endpoint.example.com/v1"
MODEL = "DeepSeek-V4-Pro"

# A debug route added to the real app so a test can ask "what would an LLM call
# made during THIS request resolve to?" — the same question every LLM call site
# answers by calling build_llm_client(). Registered once, at import.
#
# What it resolved is recorded in _RESOLVED rather than returned: on the
# default path the credential is the Azure AD token-provider *callable*, which
# has no JSON form — and a route that returned a live key would be exactly the
# thing this feature exists to avoid.
_PROBE_PATH = "/__test__/llm-endpoint"
_RESOLVED: list[tuple[object, str | None]] = []


@main_module.app.get(_PROBE_PATH)
async def _llm_endpoint_probe() -> dict:
    provider = build_llm_client()._providers[0]  # noqa: SLF001 - test introspection
    _RESOLVED.append((provider._api_key, provider._base_url))  # noqa: SLF001
    return {"recorded": True}


def _resolve(client, token: str | None = None) -> tuple[object, str | None]:
    """Issue a request (optionally presenting a token) and return the
    ``(credential, base_url)`` an LLM call during it would have used."""
    headers = {"X-Recon-Session": token} if token else {}
    client.get(_PROBE_PATH, headers=headers)
    return _RESOLVED[-1]


@pytest.fixture
def client(monkeypatch):
    """The real app, with the app's own endpoint configured and no network."""
    monkeypatch.setenv("AZURE_FOUNDRY_MODEL", MODEL)
    monkeypatch.setenv("AZURE_FOUNDRY_BASE_URL", DEFAULT_BASE)
    reset_settings_cache()
    session_override.clear_all()
    _RESOLVED.clear()
    yield TestClient(main_module.app)
    session_override.clear_all()
    _RESOLVED.clear()
    reset_settings_cache()


@pytest.fixture
def fake_probe(monkeypatch):
    """Stand in for the provider round trip: GOOD_KEY authenticates, others
    don't. Records every (key, base_url) the route actually probed."""
    calls: list[tuple[str, str | None]] = []

    def _probe(self) -> None:
        calls.append((self._api_key, self._base_url))  # noqa: SLF001
        if self._api_key != GOOD_KEY:  # noqa: SLF001
            raise ContractCompilerError(
                f"Azure AI Foundry connection test failed: 401 Unauthorized "
                f"(Authorization: Bearer {self._api_key})"  # noqa: SLF001
            )

    monkeypatch.setattr(AzureFoundryJSONClient, "probe", _probe)
    return calls


def _save(client, key=GOOD_KEY, base_url=None):
    return client.post(
        "/api/connections/override", json={"api_key": key, "base_url": base_url}
    )


# ── Acceptance 1: an invalid key fails the test and is not saved ─────────────
def test_invalid_key_test_fails_and_stores_nothing(client, fake_probe):
    res = client.post("/api/connections/test", json={"api_key": BAD_KEY})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert body["error"]
    # The probe ran against the app's default endpoint (no base URL given)…
    assert fake_probe == [(BAD_KEY, DEFAULT_BASE)]
    # …and stored nothing at all.
    assert client.get("/api/connections/status").json()["active"] is False


def test_invalid_key_cannot_be_saved(client, fake_probe):
    res = _save(client, key=BAD_KEY)
    assert res.status_code == 400
    assert "session_token" not in res.json()
    assert client.get("/api/connections/status").json()["active"] is False


def test_save_re_tests_rather_than_trusting_the_client(client, fake_probe):
    """A save is refused on its own probe, even with no prior /test call."""
    assert _save(client, key=BAD_KEY).status_code == 400
    assert fake_probe == [(BAD_KEY, DEFAULT_BASE)]


# ── Acceptance 2: a saved override is what LLM calls actually use ────────────
def test_saved_override_is_what_build_llm_client_resolves(client, fake_probe):
    token = _save(client).json()["session_token"]

    credential, base_url = _resolve(client, token)
    assert credential == GOOD_KEY
    assert base_url == DEFAULT_BASE  # blank base URL => app default


def test_custom_base_url_overrides_the_app_endpoint(client, fake_probe):
    token = _save(client, base_url=CUSTOM_BASE).json()["session_token"]

    credential, base_url = _resolve(client, token)
    assert credential == GOOD_KEY
    assert base_url == CUSTOM_BASE


def test_no_token_resolves_to_the_app_default(client, fake_probe):
    _save(client)  # an override exists, but this request does not present it
    credential, base_url = _resolve(client)
    # The default path authenticates with the Azure AD token provider — a
    # callable the SDK invokes per request — not a static key.
    assert callable(credential)
    assert base_url == DEFAULT_BASE


def test_unknown_token_resolves_to_the_app_default(client, fake_probe):
    credential, base_url = _resolve(client, "bogus")
    assert callable(credential)
    assert base_url == DEFAULT_BASE


# ── Acceptance 3: the log names the source, never the key ───────────────────
def test_log_names_the_endpoint_source_without_the_key(client, fake_probe, caplog):
    token = _save(client).json()["session_token"]

    with caplog.at_level(logging.INFO, logger="recon.llm.failover"):
        _resolve(client, token)
    override_log = caplog.text
    assert "source=session_override" in override_log
    assert f"base_url={DEFAULT_BASE}" in override_log
    assert f"model={MODEL}" in override_log
    assert GOOD_KEY not in override_log

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="recon.llm.failover"):
        _resolve(client)
    assert "source=default" in caplog.text


def test_no_route_logs_the_raw_key(client, fake_probe, caplog):
    """Every Connections request, success and failure, across every logger."""
    with caplog.at_level(logging.DEBUG):
        client.post("/api/connections/test", json={"api_key": GOOD_KEY})
        client.post("/api/connections/test", json={"api_key": BAD_KEY})
        _save(client)
        client.get("/api/connections/status")
        client.delete("/api/connections/override")
        # A malformed body on this path must not reach the 422 body-logger.
        client.post("/api/connections/test", json={"base_url": CUSTOM_BASE, "oops": GOOD_KEY})
    assert GOOD_KEY not in caplog.text
    assert BAD_KEY not in caplog.text


def test_422_on_a_sensitive_path_echoes_neither_body_nor_input(client, caplog):
    with caplog.at_level(logging.DEBUG):
        res = client.post("/api/connections/test", json={"api_key": GOOD_KEY[:0]})
    assert res.status_code == 422
    assert GOOD_KEY not in res.text
    assert "<redacted — sensitive path>" in caplog.text
    assert all("input" not in err for err in res.json()["detail"])


def test_provider_error_text_is_key_scrubbed(client, fake_probe):
    """The fake probe's message embeds the key, as a real SDK error can."""
    error = client.post("/api/connections/test", json={"api_key": BAD_KEY}).json()["error"]
    assert BAD_KEY not in error
    assert "REDACTED" in error


# ── Acceptance 4: clearing / refreshing reverts to the default ──────────────
def test_clear_reverts_to_the_default_endpoint(client, fake_probe):
    token = _save(client).json()["session_token"]
    assert client.get("/api/connections/status", headers={"X-Recon-Session": token}).json()[
        "active"
    ]

    cleared = client.delete("/api/connections/override", headers={"X-Recon-Session": token})
    assert cleared.json() == {
        "active": False,
        "source": "default",
        "cleared": True,
        "default": {"model": MODEL},
    }
    # The token is dead, so even a client that kept it is back on the default.
    assert client.get("/api/connections/status", headers={"X-Recon-Session": token}).json()[
        "active"
    ] is False
    credential, base_url = _resolve(client, token)
    assert callable(credential)
    assert base_url == DEFAULT_BASE


def test_refresh_drops_the_token_and_reverts(client, fake_probe):
    """A page refresh loses the token (it lives only in a JS variable), so the
    very next request carries none — and resolves to the default."""
    _save(client)
    credential, base_url = _resolve(client)
    assert callable(credential)
    assert base_url == DEFAULT_BASE
    assert client.get("/api/connections/status").json() == {
        "active": False,
        "source": "default",
        "default": {"model": MODEL},
    }


# ── Status disclosure ───────────────────────────────────────────────────────
def test_default_connection_discloses_only_its_model(client, fake_probe):
    """The built-in Azure connection is described by model id alone — its
    endpoint URL and auth mechanism never cross the wire."""
    # Not on any response: neither the plain status read nor a failed test
    # (whose provider error text is the user's own, but still must not carry
    # the endpoint the probe ran against).
    for res in (
        client.get("/api/connections/status"),
        client.post("/api/connections/test", json={"api_key": BAD_KEY}),
        client.delete("/api/connections/override"),
    ):
        assert DEFAULT_BASE not in res.text
        assert "DefaultAzureCredential" not in res.text

    body = client.get("/api/connections/status").json()
    assert body["default"] == {"model": MODEL}


def test_override_discloses_only_a_user_supplied_endpoint(client, fake_probe):
    """An override with no base URL of its own must not reveal the built-in
    one it is actually running against."""
    blank = _save(client).json()
    assert blank["base_url"] is None
    assert DEFAULT_BASE not in str(blank)

    own = client.post(
        "/api/connections/override", json={"api_key": GOOD_KEY, "base_url": CUSTOM_BASE}
    ).json()
    assert own["base_url"] == CUSTOM_BASE
    assert DEFAULT_BASE not in str(own)


def test_status_never_returns_the_full_key(client, fake_probe):
    saved = _save(client).json()
    token = saved["session_token"]
    assert saved["key_suffix"] == GOOD_KEY[-4:]
    # The save response itself is the first chance to leak it back.
    assert GOOD_KEY not in str(saved)

    status = client.get("/api/connections/status", headers={"X-Recon-Session": token})
    assert GOOD_KEY not in status.text
    body = status.json()
    assert body["key_suffix"] == GOOD_KEY[-4:]
    assert body["masked_key"].endswith(GOOD_KEY[-4:])
    assert body["masked_key"] != GOOD_KEY


def test_saving_again_retires_the_previous_token(client, fake_probe):
    first = _save(client).json()["session_token"]
    second = client.post(
        "/api/connections/override",
        json={"api_key": GOOD_KEY, "base_url": CUSTOM_BASE},
        headers={"X-Recon-Session": first},
    ).json()["session_token"]

    assert second != first
    assert session_override.get(first) is None
    assert session_override.get(second).base_url == CUSTOM_BASE


# ── The store itself ────────────────────────────────────────────────────────
def test_override_is_never_written_anywhere_persistent(client, fake_probe, tmp_path):
    """The whole store is one module-level dict — nothing to persist to."""
    _save(client)
    assert len(session_override._SESSIONS) == 1  # noqa: SLF001
    session_override.clear_all()
    assert session_override._SESSIONS == {}  # noqa: SLF001
    # And no file anywhere under the test's tmp dir was touched by saving.
    assert list(tmp_path.rglob("*")) == []


def test_too_short_key_is_rejected_by_the_store():
    with pytest.raises(ValueError):
        session_override.create(api_key="abc", base_url=None)


def test_mask_secrets_redacts_live_keys_and_bearer_tokens():
    session_override.clear_all()
    _, _ = session_override.create(api_key=GOOD_KEY, base_url=None)
    text = f"401 from provider: Authorization: Bearer {GOOD_KEY} rejected"
    masked = session_override.mask_secrets(text)
    assert GOOD_KEY not in masked
    assert "Bearer ***REDACTED***" in masked
    session_override.clear_all()


def test_connections_prefix_is_on_the_body_log_denylist():
    assert connections_route.router.prefix in main_module._BODY_LOG_DENYLIST  # noqa: SLF001
