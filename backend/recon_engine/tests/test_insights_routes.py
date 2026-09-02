"""HTTP-layer coverage for backend/routes/insights.py — the request shapes
the frontend actually calls (from-run-id, upload, pdf, records), mounted
standalone so this doesn't need the full app's other routers."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.recon_engine import service
from backend.recon_engine.tests.test_insights import _run_with_all_four_statuses
from backend.routes.insights import router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_from_run_id_route_returns_break_rate_payload():
    run_id = _run_with_all_four_statuses()
    client = _client()

    res = client.post("/insights/from-run-id", json={"run_id": run_id})
    assert res.status_code == 200, res.text
    payload = res.json()["payload"]
    assert payload["runId"] == run_id
    assert payload["breakRate"]["total"] == 4

    missing = client.post("/insights/from-run-id", json={"run_id": "does_not_exist"})
    assert missing.status_code == 404


def test_upload_route_accepts_the_exported_workbook_and_rejects_others():
    run_id = _run_with_all_four_statuses()
    workbook_bytes = service.build_comparison_workbook(run_id)
    client = _client()

    res = client.post(
        "/insights/upload",
        files={"file": ("results.xlsx", workbook_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert res.status_code == 200, res.text
    payload = res.json()["payload"]
    assert payload["breakRate"]["total"] == 4
    upload_id = payload["uploadId"]
    assert upload_id

    bad = client.post("/insights/upload", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert bad.status_code == 400

    # A later records/pdf call can reference the same upload without resending the file.
    records = client.post("/insights/records", json={"upload_id": upload_id, "filter": {"kind": "status", "value": "match"}})
    assert records.status_code == 200, records.text
    assert records.json()["totalMatched"] == 1


def test_pdf_route_returns_a_pdf_for_a_run():
    run_id = _run_with_all_four_statuses()
    client = _client()

    res = client.post("/insights/pdf", json={"run_id": run_id})
    assert res.status_code == 200, res.text
    assert res.content[:4] == b"%PDF"
    assert res.headers["content-disposition"].startswith("attachment")


def test_records_route_supports_csv_export():
    run_id = _run_with_all_four_statuses()
    client = _client()

    res = client.post(
        "/insights/records", json={"run_id": run_id, "filter": {"kind": "status", "value": "quantity_mismatch"}, "format": "csv"}
    )
    assert res.status_code == 200, res.text
    assert "text/csv" in res.headers["content-type"]
    assert "M2" in res.text
