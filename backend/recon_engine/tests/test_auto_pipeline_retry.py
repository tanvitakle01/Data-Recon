"""Coverage for POST /api/recon/auto-run/{id}/retry and the polled status's
`resumable` flag — resuming a hard-failed pair_values step from exactly the
batch it stopped at, never restarting the whole run.

The graph-level retry mechanism itself (retry_auto_pipeline's
update_state(..., as_node=...) call) is exercised separately in
test_graph_retry_mechanism.py; this file only covers the route's guard
conditions (404/409/200) and the immediate, synchronous status-flip side
effect — it monkeypatches retry_auto_pipeline so the background task has
nothing real to do against a synthetic graph_run_id with no actual LangGraph
checkpoint.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.routes.auto_pipeline as auto_pipeline_routes
from backend.recon_engine import run_registry
from backend.recon_engine.run_registry import RunState
from backend.recon_engine.storage import pipeline_run_store
from backend.routes.auto_pipeline import router


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(
        auto_pipeline_routes,
        "retry_auto_pipeline",
        lambda graph_run_id, on_step=None: {  # noqa: ARG005
            "status": "completed",
            "step_timestamps": {},
            "failed_step": None,
            "error": None,
        },
    )
    monkeypatch.setattr(auto_pipeline_routes, "get_pending_interrupt", lambda graph_run_id: None)  # noqa: ARG005
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _make_failed_run(graph_run_id: str, *, failed_step: str, with_checkpoint: bool) -> None:
    pipeline_run_store.create(graph_run_id)
    run_registry.transition(graph_run_id, RunState.RUNNING, reason="test setup")
    run_registry.transition(graph_run_id, RunState.FAILED, reason="test setup")
    pipeline_run_store.update_progress(
        graph_run_id,
        failed_step=failed_step,
        error="All configured AI providers are unavailable for value-pairing.",
    )
    if with_checkpoint:
        pipeline_run_store.save_batch_checkpoint(
            graph_run_id,
            field_pair="Material -> PRDID",
            next_batch_index=2,
            batch_count=4,
            matches=[{"source_value": "A", "target_value": "A"}],
        )


def test_retry_404s_for_unknown_run(client):
    res = client.post("/api/recon/auto-run/does-not-exist/retry")
    assert res.status_code == 404


def test_retry_409s_when_run_is_not_failed(client):
    pipeline_run_store.create("autorun_running")
    res = client.post("/api/recon/auto-run/autorun_running/retry")
    assert res.status_code == 409


def test_retry_409s_when_failed_step_is_not_pair_values(client):
    _make_failed_run("autorun_other_step", failed_step="resolve_schema", with_checkpoint=False)
    res = client.post("/api/recon/auto-run/autorun_other_step/retry")
    assert res.status_code == 409


def test_retry_409s_when_no_batch_completed_yet(client):
    _make_failed_run("autorun_no_checkpoint", failed_step="run_batches", with_checkpoint=False)
    res = client.post("/api/recon/auto-run/autorun_no_checkpoint/retry")
    assert res.status_code == 409


def _make_failed_run_batches_run(graph_run_id: str) -> None:
    """Like ``_make_failed_run``, but for a live-connector (non-from-data) run
    — its batch checkpoint lives in ``run_batch_checkpoint`` (keyed by
    graph_run_id alone, one batch covering extraction+pairing+reconcile
    together), not the from-data graph's field-pair-keyed
    ``pipeline_batch_checkpoints``. See ``_has_resumable_checkpoint`` in
    ``routes/auto_pipeline.py``."""
    pipeline_run_store.create(graph_run_id)
    run_registry.transition(graph_run_id, RunState.RUNNING, reason="test setup")
    run_registry.transition(graph_run_id, RunState.FAILED, reason="test setup")
    pipeline_run_store.update_progress(
        graph_run_id,
        failed_step="run_batches",
        error="Batch 3 failed: All configured AI providers are unavailable for value-pairing.",
    )
    pipeline_run_store.save_run_batch_checkpoint(
        graph_run_id,
        result_id="result_test",
        next_batch_index=2,
        batch_count=4,
        summary={"total": 0, "match": 0, "quantity_mismatch": 0, "mismatch": 0, "excluded_unmapped": {}},
    )


def test_retry_succeeds_and_flips_status_to_running(client):
    _make_failed_run_batches_run("autorun_resumable")
    res = client.post("/api/recon/auto-run/autorun_resumable/retry")
    assert res.status_code == 200, res.text
    assert res.json()["graph_run_id"] == "autorun_resumable"
    # The route handler flips status to "running" synchronously before the
    # background task even starts; the background task itself (retry_auto_
    # pipeline, monkeypatched here to resolve instantly) may have already
    # completed it to "completed" by the time this assertion runs under
    # TestClient's portal — either is a valid post-retry state, "failed" is not.
    assert pipeline_run_store.get("autorun_resumable")["status"] in {"running", "completed"}


def test_status_reports_resumable_true_only_with_a_pair_values_checkpoint(client):
    _make_failed_run_batches_run("autorun_status_check")
    res = client.get("/api/recon/auto-run/autorun_status_check/status")
    assert res.status_code == 200
    assert res.json()["resumable"] is True


def test_status_reports_resumable_false_without_a_checkpoint(client):
    _make_failed_run("autorun_status_no_checkpoint", failed_step="run_batches", with_checkpoint=False)
    res = client.get("/api/recon/auto-run/autorun_status_no_checkpoint/status")
    assert res.status_code == 200
    assert res.json()["resumable"] is False


def test_status_reports_resumable_false_for_a_non_pair_values_failure(client):
    _make_failed_run("autorun_status_other_step", failed_step="finalize", with_checkpoint=False)
    res = client.get("/api/recon/auto-run/autorun_status_other_step/status")
    assert res.status_code == 200
    assert res.json()["resumable"] is False
