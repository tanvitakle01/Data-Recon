"""POST /api/recon/mapping-sheet/identify — route wiring + allow-list surface.

The LLM is faked; the assertions cover the HTTP contract the frontend relies on
(auto-selected connector + evidence, and the flag-not-coerce path), not model
quality.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.recon_engine import sheet_identifier
from backend.routes.contracts import router


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class _FakeClient:
    def __init__(self, payload):
        self._payload = payload

    def complete_json(self, messages):  # noqa: ARG002
        return self._payload


@pytest.fixture
def fake_llm(monkeypatch):
    monkeypatch.setattr(
        sheet_identifier, "get_settings", lambda: type("S", (), {"any_llm_configured": True})()
    )

    def _install(payload):
        monkeypatch.setattr(sheet_identifier, "build_llm_client", lambda: _FakeClient(payload))

    return _install


def test_identify_route_never_autoselects_a_connector(client, fake_llm):
    """Stage-1 is file-upload only — there is no live-connector registry, so a
    named kind is always surfaced as evidence/a warning, never auto-selected
    into a connector_id (see ``recon_engine.connector_registry``, which is
    permanently empty)."""
    fake_llm(
        {
            "source": {"kind": "s4", "evidence": "VBAP/VBEP table prefixes", "confidence": "high", "fields": ["Material"]},
            "target": {"kind": "ibp", "evidence": "Target: IBP banner", "confidence": "high", "fields": ["PRDID"]},
        }
    )
    resp = client.post("/api/recon/mapping-sheet/identify", json={"mapping_sheet": {"headers": ["Source Table/Field"]}})
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"]["kind"] is None  # not coerced to s4
    assert body["source"]["connector_id"] is None
    assert body["target"]["connector_id"] is None
    assert body["source"]["evidence"]
    assert body["degraded"] is False
    assert any("s4" in w.lower() for w in body["warnings"])


def test_identify_route_flags_unregistered_connector(client, fake_llm):
    fake_llm(
        {
            "source": {"kind": "bw", "evidence": "BW InfoObject naming", "confidence": "high", "fields": []},
            "target": {"kind": "ibp", "evidence": "IBP", "confidence": "high", "fields": []},
        }
    )
    resp = client.post("/api/recon/mapping-sheet/identify", json={"mapping_sheet": {}})
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"]["kind"] is None  # not coerced to s4
    assert body["source"]["connector_id"] is None
    assert any("bw" in w.lower() for w in body["warnings"])


def test_identify_route_empty_body_degrades(client):
    # No LLM configured (conftest clears keys) → 200 with a degraded result,
    # never a 500 — the wizard just falls back to manual selection.
    resp = client.post("/api/recon/mapping-sheet/identify", json={})
    assert resp.status_code == 200
    assert resp.json()["degraded"] is True
