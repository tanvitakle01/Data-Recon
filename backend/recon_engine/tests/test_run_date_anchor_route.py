"""HTTP-level coverage for the ``anchor_date`` override on POST
/shadow-preview and POST /runs, and the new GET /runs/{run_id}/date-alignment
diagnostic — exercised through the real FastAPI router.
"""

from __future__ import annotations

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
    """Same rollforward stand-in as test_run_date_anchor.py: a source date
    safely in the past always gets reassigned to anchor + 1 day, and the
    frozen target extract's date only lines up for one specific anchor."""
    source_df = pd.DataFrame({
        "PRDID": ["786293"], "LOCID": ["3340"], "KEYFIGUREDATE": ["2020-01-01"], "QTY": [5],
    })
    target_df = pd.DataFrame({
        "PRDID": ["786293"], "LOCID": ["3340"], "KEYFIGUREDATE": ["2026-01-02"], "QTY": [5],
    })
    src_snap = service.ingest_snapshot(source_df, layer=RawLayer.SOURCE, source_type="excel")
    tgt_snap = service.ingest_snapshot(target_df, layer=RawLayer.TARGET, source_type="excel")

    mapping_sheet = [
        {"source_col": "PRDID", "target_col": "PRDID", "role": "key"},
        {"source_col": "LOCID", "target_col": "LOCID", "role": "key"},
        {"source_col": "KEYFIGUREDATE", "target_col": "KEYFIGUREDATE", "role": "key"},
        {"source_col": "QTY", "target_col": "QTY", "role": "compare"},
    ]
    draft, _ = service.compile_draft(
        mapping_sheet=mapping_sheet, rules="",
        business_key=[
            {"source_field": "PRDID", "target_field": "PRDID"},
            {"source_field": "LOCID", "target_field": "LOCID"},
            {"source_field": "KEYFIGUREDATE", "target_field": "KEYFIGUREDATE"},
        ],
        compare_fields=[{"source_field": "QTY", "target_field": "QTY"}],
        source_schema=list(source_df.columns), target_schema=list(target_df.columns),
        comparison_type="custom", source_type="excel", target_type="excel",
        compiler=StubContractCompiler(),
    )
    draft.operations = [
        {
            "op": "date_window_filter", "field": "KEYFIGUREDATE",
            "params": {"lower_offset_days": -3650, "upper_offset_days": 3650},
        },
        {
            "op": "relative_date_reassign", "field": "KEYFIGUREDATE",
            "params": {"date_condition": "lt", "offset_days": 1},
        },
    ]
    contract = service.approve_contract(draft, approved_by="alice")
    return contract, src_snap, tgt_snap


def test_shadow_preview_route_accepts_anchor_date(client):
    contract, src_snap, tgt_snap = _setup()
    res = client.post("/api/recon/shadow-preview", json={
        "contract_id": contract.contract_id,
        "source_snapshot_id": src_snap.snapshot_id,
        "target_snapshot_id": tgt_snap.snapshot_id,
        "anchor_date": "2026-01-01",
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["shadow"]["rows"][0]["KEYFIGUREDATE"] == "2026-01-02"
    assert body["anchor_date"] == "2026-01-01"
    assert body["anchor_resolver"] == "explicit"


def test_run_route_matches_with_the_right_anchor_and_misses_with_the_wrong_one(client):
    contract, src_snap, tgt_snap = _setup()
    body = {
        "contract_id": contract.contract_id,
        "source_snapshot_id": src_snap.snapshot_id,
        "target_snapshot_id": tgt_snap.snapshot_id,
    }

    right = client.post("/api/recon/runs", json={**body, "anchor_date": "2026-01-01"})
    assert right.status_code == 200, right.text
    assert right.json()["summary"]["match"] == 1
    assert right.json()["run"]["anchor_resolver"] == "explicit"

    wrong = client.post("/api/recon/runs", json={**body, "anchor_date": "2026-02-01"})
    assert wrong.status_code == 200, wrong.text
    assert wrong.json()["summary"]["match"] == 0


def test_run_date_alignment_route_flags_no_overlap_for_the_wrong_anchor(client):
    contract, src_snap, tgt_snap = _setup()
    run = client.post("/api/recon/runs", json={
        "contract_id": contract.contract_id,
        "source_snapshot_id": src_snap.snapshot_id,
        "target_snapshot_id": tgt_snap.snapshot_id,
        "anchor_date": "2026-02-01",
    }).json()

    res = client.get(f"/api/recon/runs/{run['run_id']}/date-alignment")
    assert res.status_code == 200, res.text
    alignment = res.json()["alignment"]
    assert alignment["has_overlap"] is False


def test_run_date_alignment_route_404s_for_unknown_run(client):
    res = client.get("/api/recon/runs/not-a-real-run/date-alignment")
    assert res.status_code == 404
