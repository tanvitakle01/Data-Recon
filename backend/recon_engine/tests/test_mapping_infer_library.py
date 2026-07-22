"""POST /api/recon/mapping/infer — three-tier provenance (library → LLM).

The LLM is faked; assertions cover the tier routing and provenance labels the
mapping card relies on, not model quality. Proves: cold start hits the LLM and
labels the provider; a subsequent identical column set (any order) is served
from the library with NO LLM call; Regenerate forces the LLM back.
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.recon_engine import field_mapper
from backend.recon_engine.models.attribute_mapping import AttributePair
from backend.recon_engine.storage import attribute_mapping_store as store
from backend.routes.mapping_infer import router


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class _FakeClient:
    def complete_json(self, messages):  # noqa: ARG002
        return {
            "mappings": [
                {"source_column": "Material", "target_column": "PRDID", "role": "Key", "reason": "id-like"},
                {"source_column": "Qty", "target_column": "SALES", "role": "Compare", "reason": "quantity"},
            ]
        }


class _Outcome:
    provider_used = "groq"
    fallback_occurred = False
    notice = None


@pytest.fixture
def fake_llm(monkeypatch):
    """Install a working fake Groq client + configured settings + outcome."""
    monkeypatch.setattr(
        field_mapper, "get_settings", lambda: type("S", (), {"any_llm_configured": True})()
    )
    monkeypatch.setattr(field_mapper, "build_llm_client", lambda: _FakeClient())
    monkeypatch.setattr(field_mapper, "get_last_llm_outcome", lambda: _Outcome())


def _form(**overrides):
    form = {
        "source_rows": json.dumps([{"Material": "M1", "Qty": "5"}]),
        "target_rows": json.dumps([{"PRDID": "P1", "SALES": "5"}]),
        "source_connector": "s4",
        "target_connector": "ibp",
        "comparison_type": "soh",
        "source_columns": json.dumps(["Material", "Qty"]),
        "target_columns": json.dumps(["PRDID", "SALES"]),
    }
    form.update(overrides)
    return form


def test_cold_start_uses_llm_and_labels_provider(client, fake_llm):
    resp = client.post("/api/recon/mapping/infer", data=_form())
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "llm"
    assert body["provider"] == "groq"
    assert body["display"]  # something was inferred
    assert {row["provenance"] for row in body["display"]} == {"groq"}


def test_second_run_same_columns_any_order_hits_library_no_llm(client, monkeypatch):
    # A prior run stored this mapping (store-back), columns in one order …
    store.upsert(
        source_connector="s4", target_connector="ibp", comparison_type="soh",
        source_columns=["Qty", "Material"], target_columns=["SALES", "PRDID"],
        mappings=[
            AttributePair(source_col="Material", target_col="PRDID", role="key"),
            AttributePair(source_col="Qty", target_col="SALES", role="compare"),
        ],
        confidence=0.88,
    )

    # The LLM must NOT be consulted on a library hit — make it explode if it is.
    def _boom():
        raise AssertionError("LLM was called on a library hit")

    monkeypatch.setattr(field_mapper, "build_llm_client", _boom)

    # … now the same set is requested in a DIFFERENT order.
    resp = client.post(
        "/api/recon/mapping/infer",
        data=_form(source_columns=json.dumps(["Material", "Qty"]),
                   target_columns=json.dumps(["PRDID", "SALES"])),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "library"
    assert body["provider"] is None
    assert {row["provenance"] for row in body["display"]} == {"library"}


def test_regenerate_forces_llm_even_with_library_hit(client, fake_llm):
    store.upsert(
        source_connector="s4", target_connector="ibp", comparison_type="soh",
        source_columns=["Material", "Qty"], target_columns=["PRDID", "SALES"],
        mappings=[AttributePair(source_col="Material", target_col="PRDID", role="key")],
    )
    resp = client.post("/api/recon/mapping/infer", data=_form(regenerate="true"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "llm"  # dropped to tier 2 despite the stored entry
    assert body["provider"] == "groq"
    assert {row["provenance"] for row in body["display"]} == {"groq"}
