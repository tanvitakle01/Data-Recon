"""HTTP-level coverage for the Review-Changes checkpoint: POST /shadow-preview
and the /runs fingerprint guard, exercised through the real FastAPI router.

The approved contract + snapshots are set up via the service (bypassing the
LLM compile route, which may hit a live Groq key) so the test is deterministic;
only the new HTTP surface is exercised through the client.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.recon_engine import service
from backend.recon_engine.compiler import StubContractCompiler
from backend.recon_engine.models.snapshot import RawLayer
from backend.routes.recon_v2 import router


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _setup():
    source_df = pd.DataFrame({"Plant": ["5006"], "Material": ["N01-FG01"], "Qty": [100]})
    target_df = pd.DataFrame({"LOCID": ["PL5006@S21400"], "PRDID": ["T01-FG01"], "QTY": [100]})
    src_snap = service.ingest_snapshot(source_df, layer=RawLayer.SOURCE, source_type="excel")
    tgt_snap = service.ingest_snapshot(target_df, layer=RawLayer.TARGET, source_type="excel")

    mapping_sheet = [
        {"source_col": "Plant", "target_col": "LOCID", "role": "key",
         "transformation": "Add prefix PL; Append @S21400"},
        {"source_col": "Material", "target_col": "PRDID", "role": "key",
         "transformation": "Replace N01 with T01"},
        {"source_col": "Qty", "target_col": "QTY", "role": "compare"},
    ]
    draft, _ = service.compile_draft(
        mapping_sheet=mapping_sheet, rules="",
        business_key=[
            {"source_field": "Plant", "target_field": "LOCID"},
            {"source_field": "Material", "target_field": "PRDID"},
        ],
        compare_fields=[{"source_field": "Qty", "target_field": "QTY"}],
        source_schema=["Plant", "Material", "Qty"], target_schema=["LOCID", "PRDID", "QTY"],
        comparison_type="custom", source_type="excel", target_type="excel",
        compiler=StubContractCompiler(),
    )
    contract = service.approve_contract(draft, approved_by="alice")
    return contract, src_snap, tgt_snap


def test_shadow_preview_route_returns_diffs_and_fingerprint(client):
    contract, src_snap, tgt_snap = _setup()

    res = client.post("/api/recon/shadow-preview", json={
        "contract_id": contract.contract_id,
        "source_snapshot_id": src_snap.snapshot_id,
        "target_snapshot_id": tgt_snap.snapshot_id,
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["shadow"]["rows"][0]["Plant"] == "PL5006@S21400"
    assert body["target"]["rows"][0]["PRDID"] == "T01-FG01"
    assert body["shadow_fingerprint"]


def test_run_route_enforces_fingerprint(client):
    contract, src_snap, tgt_snap = _setup()
    preview = client.post("/api/recon/shadow-preview", json={
        "contract_id": contract.contract_id,
        "source_snapshot_id": src_snap.snapshot_id,
        "target_snapshot_id": tgt_snap.snapshot_id,
    }).json()
    fingerprint = preview["shadow_fingerprint"]

    body = {
        "contract_id": contract.contract_id,
        "contract_version": contract.contract_version,
        "source_snapshot_id": src_snap.snapshot_id,
        "target_snapshot_id": tgt_snap.snapshot_id,
    }

    ok = client.post("/api/recon/runs", json={**body, "expected_shadow_fingerprint": fingerprint})
    assert ok.status_code == 200, ok.text
    assert ok.json()["summary"]["match"] == 1

    stale = client.post("/api/recon/runs", json={**body, "expected_shadow_fingerprint": "sha256:bad"})
    assert stale.status_code == 409, stale.text


def test_snapshot_upload_accepts_large_rows_payload(client):
    """A SAP-fetched dataset sent as a >1MB multipart `rows` field must ingest
    successfully — the previous Form()/File() route tripped Starlette's 1MB
    per-part cap ('Part exceeded maximum size of 1024KB.')."""
    rows = [{"Plant": f"P{i:05d}", "Material": "N01-FG01", "Qty": i} for i in range(20000)]
    payload = json.dumps(rows)
    assert len(payload.encode()) > 1024 * 1024, "payload must exceed the old 1MB cap"

    # A dummy file forces httpx to encode the body as multipart/form-data (the
    # transport the browser's FormData uses); the route only reads a part named
    # 'file', so 'dummy' is ignored.
    res = client.post(
        "/api/recon/snapshots/upload",
        data={"layer": "Raw_Source", "source_type": "s4", "rows": payload},
        files={"dummy": ("dummy.txt", b"x")},
    )
    assert res.status_code == 200, res.text
    assert res.json()["snapshot"]["row_count"] == 20000
