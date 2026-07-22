"""Connector registry allow-list — the set the LLM identification is bound to."""

from __future__ import annotations

from backend.API_conn.connectors import registry


def _cfg(s4_enabled=True, ibp_enabled=True):
    base = {
        "base_url": "https://x",
        "service": "SRV",
        "username": "u",
        "password": "p",
    }
    return {
        "s4": {"enabled": s4_enabled, **base},
        "ibp": {"enabled": ibp_enabled, **base},
    }


def test_configured_kinds_are_s4_and_ibp():
    kinds = registry.configured_kinds(config=_cfg())
    assert kinds == {"s4", "ibp"}


def test_role_allow_lists_are_disjoint():
    source = registry.get_configured_connectors(config=_cfg(), role=registry.SOURCE)
    target = registry.get_configured_connectors(config=_cfg(), role=registry.TARGET)
    assert [c["kind"] for c in source] == ["s4"]
    assert [c["kind"] for c in target] == ["ibp"]
    # UI connector ids are carried through for auto-select.
    assert source[0]["connector_id"] == "sap_s4hana"
    assert target[0]["connector_id"] == "sap_ibp"


def test_disabled_flag_is_honored():
    # enabled:false removes the connector from the configured allow-list.
    assert registry.configured_kinds(config=_cfg(s4_enabled=False)) == {"ibp"}


def test_missing_credentials_means_unconfigured():
    cfg = {"s4": {"enabled": True, "base_url": "https://x"}}  # no service/user/pass
    assert registry.configured_kinds(config=cfg) == set()


def test_is_registered_kind():
    # Real, in-code connectors are registered; aspirational ones are not.
    assert registry.is_registered_kind("s4") is True
    assert registry.is_registered_kind("ibp") is True
    assert registry.is_registered_kind("bw") is False
    assert registry.is_registered_kind("ecc") is False
    assert registry.is_registered_kind(None) is False


def test_missing_config_file_degrades_to_empty(monkeypatch):
    # A registry that can't read config reports "nothing configured", not a crash.
    monkeypatch.setattr(registry, "load_config", lambda: (_ for _ in ()).throw(FileNotFoundError()))
    assert registry.get_configured_connectors() == []
