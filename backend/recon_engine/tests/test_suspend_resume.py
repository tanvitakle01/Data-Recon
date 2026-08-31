"""Coverage for SUSPEND/RESUME + the Stored Runs API.

Mirrors ``test_auto_pipeline_retry.py``'s approach: monkeypatch the graph-level
suspend/resume functions and drive the FastAPI routes directly — the ONE new
LangGraph mechanism this feature depends on (``update_state(..., as_node=...)``
resuming after a "suspended" status, not just a "failed" one) is proven
separately below in a synthetic graph, the same way
``test_graph_retry_mechanism.py`` proves the retry case.
"""

from __future__ import annotations

import sqlite3
from typing import TypedDict

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

import backend.routes.auto_pipeline as auto_pipeline_routes
from backend.recon_engine import run_registry
from backend.recon_engine.run_registry import RunState
from backend.recon_engine.storage import corroboration_store, pipeline_run_store
from backend.routes.auto_pipeline import router


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(
        auto_pipeline_routes, "resume_suspended_pipeline",
        lambda graph_run_id, on_step=None: {  # noqa: ARG005
            "status": "completed", "step_timestamps": {}, "failed_step": None, "error": None,
        },
    )
    monkeypatch.setattr(auto_pipeline_routes, "get_pending_interrupt", lambda graph_run_id: None)  # noqa: ARG005
    monkeypatch.setattr(auto_pipeline_routes, "_capture_fingerprint_for", lambda graph_run_id: None)  # noqa: ARG005
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _make_running_batch_plan_run(graph_run_id: str) -> None:
    pipeline_run_store.create(graph_run_id)
    run_registry.transition(graph_run_id, RunState.RUNNING, reason="test setup")
    pipeline_run_store.save_run_batch_plan(graph_run_id, [{"batch_index": i} for i in range(4)])
    pipeline_run_store.save_run_batch_checkpoint(
        graph_run_id, result_id="result_test", next_batch_index=2, batch_count=4,
        summary={"total": 0, "match": 0, "quantity_mismatch": 0, "mismatch": 0, "excluded_unmapped": {}},
    )


def _make_failed_resumable_run(graph_run_id: str) -> None:
    pipeline_run_store.create(graph_run_id)
    run_registry.transition(graph_run_id, RunState.RUNNING, reason="test setup")
    run_registry.transition(graph_run_id, RunState.FAILED, reason="test setup")
    pipeline_run_store.update_progress(graph_run_id, failed_step="run_batches", error="network error")
    pipeline_run_store.save_run_batch_checkpoint(
        graph_run_id, result_id="result_test", next_batch_index=2, batch_count=4,
        summary={"total": 0, "match": 0, "quantity_mismatch": 0, "mismatch": 0, "excluded_unmapped": {}},
    )


# ── suspend route ────────────────────────────────────────────────────────────

def test_suspend_404s_for_unknown_run(client):
    res = client.post("/api/recon/auto-run/does-not-exist/suspend", json={})
    assert res.status_code == 404


def test_suspend_409s_when_run_is_waiting_for_input(client):
    pipeline_run_store.create("autorun_waiting")
    run_registry.transition("autorun_waiting", RunState.RUNNING, reason="test setup")
    run_registry.transition("autorun_waiting", RunState.PAUSED_FOR_INPUT, reason="test setup")
    res = client.post("/api/recon/auto-run/autorun_waiting/suspend", json={})
    assert res.status_code == 409


def test_suspend_parks_a_running_run_cooperatively(client):
    _make_running_batch_plan_run("autorun_to_suspend")
    res = client.post("/api/recon/auto-run/autorun_to_suspend/suspend", json={"reason": "user paused"})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "suspending"
    assert run_registry.current_state("autorun_to_suspend") == RunState.SUSPENDING
    suspension = pipeline_run_store.get_suspension("autorun_to_suspend")
    assert suspension is not None
    assert suspension["suspend_reason"] == "user paused"


def test_suspend_converts_a_failed_resumable_run_directly(client):
    _make_failed_resumable_run("autorun_failed_to_suspend")
    res = client.post("/api/recon/auto-run/autorun_failed_to_suspend/suspend", json={})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "suspended"
    assert run_registry.current_state("autorun_failed_to_suspend") == RunState.SUSPENDED


def test_suspend_409s_for_a_failed_run_with_nothing_resumable(client):
    pipeline_run_store.create("autorun_failed_no_checkpoint")
    run_registry.transition("autorun_failed_no_checkpoint", RunState.RUNNING, reason="test setup")
    run_registry.transition("autorun_failed_no_checkpoint", RunState.FAILED, reason="test setup")
    pipeline_run_store.update_progress("autorun_failed_no_checkpoint", failed_step="resolve_schema", error="boom")
    res = client.post("/api/recon/auto-run/autorun_failed_no_checkpoint/suspend", json={})
    assert res.status_code == 409


# ── resume route ─────────────────────────────────────────────────────────────

def _make_suspended_run(graph_run_id: str, *, fingerprint: dict | None = None) -> None:
    pipeline_run_store.create(graph_run_id)
    run_registry.transition(graph_run_id, RunState.RUNNING, reason="test setup")
    run_registry.transition(graph_run_id, RunState.SUSPENDING, reason="test setup")
    run_registry.transition(graph_run_id, RunState.SUSPENDED, reason="test setup")
    pipeline_run_store.save_run_batch_checkpoint(
        graph_run_id, result_id="result_test", next_batch_index=2, batch_count=4,
        summary={"total": 0, "match": 0, "quantity_mismatch": 0, "mismatch": 0, "excluded_unmapped": {}},
    )
    pipeline_run_store.save_suspension(
        graph_run_id, user_name="test", suspend_reason="test",
        data_fingerprint=fingerprint or {}, expires_at="2999-01-01T00:00:00+00:00",
    )


def test_resume_404s_for_unknown_run(client):
    res = client.post("/api/recon/auto-run/does-not-exist/resume", json={})
    assert res.status_code == 404


def test_resume_409s_when_not_suspended(client):
    pipeline_run_store.create("autorun_not_suspended")
    res = client.post("/api/recon/auto-run/autorun_not_suspended/resume", json={})
    assert res.status_code == 409


def test_resume_succeeds_and_flips_status_to_running(client):
    _make_suspended_run("autorun_resumable_suspend")
    res = client.post("/api/recon/auto-run/autorun_resumable_suspend/resume", json={})
    assert res.status_code == 200, res.text
    assert pipeline_run_store.get("autorun_resumable_suspend")["status"] in {"running", "completed"}
    # The suspension record survives resuming — Stored Runs tracks a run
    # through resume/completion until the user explicitly deletes it.
    assert pipeline_run_store.get_suspension("autorun_resumable_suspend") is not None


def test_resume_409s_on_stale_fingerprint(client, monkeypatch):
    _make_suspended_run("autorun_stale", fingerprint={
        "source": {"row_count": 10, "max_date": "2024-01-01"},
        "target": {"row_count": 10, "max_date": "2024-01-01"},
    })
    monkeypatch.setattr(
        auto_pipeline_routes, "_capture_fingerprint_for",
        lambda graph_run_id: {  # noqa: ARG005
            "source": {"row_count": 999, "max_date": "2024-06-01"},
            "target": {"row_count": 10, "max_date": "2024-01-01"},
        },
    )
    res = client.post("/api/recon/auto-run/autorun_stale/resume", json={})
    assert res.status_code == 409
    assert run_registry.current_state("autorun_stale") == RunState.SUSPENDED

    # force=true proceeds despite the mismatch.
    res = client.post("/api/recon/auto-run/autorun_stale/resume", json={"force": True})
    assert res.status_code == 200, res.text


# ── stored runs listing + delete ────────────────────────────────────────────

def test_stored_runs_lists_only_currently_suspended_runs(client):
    _make_suspended_run("autorun_listed")
    pipeline_run_store.create("autorun_not_listed")
    run_registry.transition("autorun_not_listed", RunState.RUNNING, reason="test setup")

    res = client.get("/api/recon/auto-run/stored")
    assert res.status_code == 200
    ids = {row["graph_run_id"] for row in res.json()}
    assert "autorun_listed" in ids
    assert "autorun_not_listed" not in ids
    row = next(r for r in res.json() if r["graph_run_id"] == "autorun_listed")
    assert row["batches_completed"] == 2
    assert row["batches_total"] == 4


def test_delete_stored_run_cancels_and_cleans_up_artifacts(client):
    _make_suspended_run("autorun_to_delete")
    corroboration_store.record_batch_evidence(
        "autorun_to_delete", source_field="Material", target_field="PRDID",
        source_value="A", target_value="A", source_seen=True, target_seen=True, overlap=True,
    )

    res = client.delete("/api/recon/auto-run/autorun_to_delete")
    assert res.status_code == 200, res.text
    assert run_registry.current_state("autorun_to_delete") == RunState.CANCELLED
    assert pipeline_run_store.get_suspension("autorun_to_delete") is None
    assert pipeline_run_store.get_run_batch_checkpoint("autorun_to_delete") is None
    assert corroboration_store.get_overlap(
        "autorun_to_delete", source_field="Material", target_field="PRDID",
        source_value="A", target_value="A",
    ) is None


def test_delete_stored_run_404s_when_never_a_stored_run(client):
    # Never suspended — no pipeline_run_suspensions row — so it isn't a Stored
    # Runs entry at all, distinct from the 409 an ACTIVE run gets below.
    pipeline_run_store.create("autorun_not_suspended_delete")
    res = client.delete("/api/recon/auto-run/autorun_not_suspended_delete")
    assert res.status_code == 404


def test_delete_stored_run_409s_while_active(client):
    # Transition directly rather than via the real /resume (which kicks off
    # a background graph re-execution this synthetic run's incomplete state
    # can't actually support) — this test only cares about the DELETE route's
    # ACTIVE_STATES guard, not resume's own machinery (covered above).
    _make_suspended_run("autorun_delete_while_running")
    run_registry.transition("autorun_delete_while_running", RunState.RUNNING, reason="test setup")
    res = client.delete("/api/recon/auto-run/autorun_delete_while_running")
    assert res.status_code == 409


def test_delete_stored_run_dismisses_a_completed_tracked_run(client):
    _make_suspended_run("autorun_delete_completed")
    run_registry.transition("autorun_delete_completed", RunState.RUNNING, reason="test setup")
    run_registry.transition("autorun_delete_completed", RunState.COMPLETED, reason="test setup")

    res = client.delete("/api/recon/auto-run/autorun_delete_completed")
    assert res.status_code == 200, res.text
    assert pipeline_run_store.get_suspension("autorun_delete_completed") is None
    # A completed run's status is terminal — never touched by delete.
    assert run_registry.current_state("autorun_delete_completed") == RunState.COMPLETED


# ── partial results without resuming ────────────────────────────────────────

def test_partial_results_available_without_resuming(client, monkeypatch):
    from backend.recon_engine.storage import result_store
    from backend.recon_engine.models.results import ReconciliationSummary
    import pandas as pd

    _make_suspended_run("autorun_partial_results")
    result = result_store.start_streaming_result(
        run_id="autorun_partial_results", contract_id="c1", contract_version=1
    )
    # Real batches stamp run_id/batch_id/record_id onto every detail row (see
    # auto_pipeline.nodes._do_run_batches) and record a matching
    # run_batch_attempts row — both are what let the View panel group rows by
    # batch number, so this test reproduces them rather than a bare frame.
    result_store.append_batch_result(
        result.result_id,
        detail_df=pd.DataFrame({
            "source_value": ["A"], "target_value": ["A"],
            "run_id": ["autorun_partial_results"], "batch_id": ["batch_1"], "record_id": ["rec_1"],
        }),
        batch_summary=ReconciliationSummary(total=1, match=1),
    )
    pipeline_run_store.record_batch_attempt(
        "autorun_partial_results", batch_id="batch_1", batch_index=0,
        supersedes_batch_id=None, status="completed",
    )

    res = client.get("/api/recon/auto-run/autorun_partial_results/partial-results")
    assert res.status_code == 200
    body = res.json()
    assert body["batches_completed"] == 1
    assert body["batches"][0]["batch_index"] == 0
    assert body["batches"][0]["preview_rows"] == [
        {
            "source_value": "A", "target_value": "A",
            "run_id": "autorun_partial_results", "batch_id": "batch_1", "record_id": "rec_1",
        }
    ]
    # No value mappings were recorded for this batch — an empty list, not a
    # missing key (the frontend renders nothing for an empty batch mapping).
    assert body["batches"][0]["mappings"] == []

    res = client.get("/api/recon/auto-run/autorun_partial_results/partial-results/export")
    assert res.status_code == 200
    assert "source_value" in res.text
    assert "1of" in res.headers["content-disposition"]


def test_partial_results_includes_this_batchs_value_mappings(client):
    from backend.recon_engine.storage import result_store, run_value_mapping_store
    from backend.recon_engine.models.results import ReconciliationSummary
    from backend.recon_engine.models.value_mapping import ValueMapping
    import pandas as pd

    _make_suspended_run("autorun_partial_mappings")
    result = result_store.start_streaming_result(
        run_id="autorun_partial_mappings", contract_id="c1", contract_version=1
    )
    result_store.append_batch_result(
        result.result_id,
        detail_df=pd.DataFrame({
            "source_value": ["A"], "target_value": ["A"],
            "run_id": ["autorun_partial_mappings"], "batch_id": ["batch_1"], "record_id": ["rec_1"],
        }),
        batch_summary=ReconciliationSummary(total=1, match=1),
    )
    pipeline_run_store.record_batch_attempt(
        "autorun_partial_mappings", batch_id="batch_1", batch_index=0,
        supersedes_batch_id=None, status="completed",
    )
    run_value_mapping_store.record_batch_mapping(
        "autorun_partial_mappings",
        ValueMapping.model_validate({
            "source_field": "Material", "target_field": "PRDID",
            "matches": [
                {"source_value": "A", "target_value": "A1", "confidence": "high",
                 "rule": "t", "evidence": "e", "row_count": 1},
            ],
        }),
        batch_id="batch_1",
    )

    res = client.get("/api/recon/auto-run/autorun_partial_mappings/partial-results")
    assert res.status_code == 200
    mappings = res.json()["batches"][0]["mappings"]
    assert len(mappings) == 1
    assert mappings[0]["source_field"] == "Material"
    assert mappings[0]["matches"][0]["source_value"] == "A"
    assert mappings[0]["matches"][0]["target_value"] == "A1"


def test_stored_runs_and_partial_results_fall_back_to_batch_progress_when_checkpoint_is_gone(client):
    """Reproduces a run that hard-failed at ``finalize`` AFTER every batch
    completed: its checkpoint/plan are already gone (``_do_finalize`` clears
    them once ``run_batches`` itself is done, regardless of whether finalize
    then succeeds), but ``batch_progress_json`` — a separate, never-cleared
    field — still has the real count. Both ``list_stored_runs`` and
    ``get_partial_results`` must report the true 6-of-6, not a misleading
    0-of-unknown."""
    graph_run_id = "autorun_finalize_failed_progress"
    _make_suspended_run(graph_run_id)
    run_registry.transition(graph_run_id, RunState.RUNNING, reason="test setup")
    pipeline_run_store.update_batch_progress(
        graph_run_id, field_pair="Material -> PRDID", batch_index=5, batch_count=6,
        batch_label="batch 6", stage="completed", batches_completed=6,
    )
    run_registry.transition(graph_run_id, RunState.FAILED, reason="test setup")
    pipeline_run_store.update_progress(graph_run_id, failed_step="finalize", error="0 columns passed")
    pipeline_run_store.clear_run_batch_state(graph_run_id)  # what _do_finalize does before it can fail

    res = client.get("/api/recon/auto-run/stored")
    assert res.status_code == 200
    row = next(r for r in res.json() if r["graph_run_id"] == graph_run_id)
    assert row["batches_completed"] == 6
    assert row["batches_total"] == 6

    res = client.get(f"/api/recon/auto-run/{graph_run_id}/partial-results")
    assert res.status_code == 200
    assert res.json()["batches_total"] == 6


def test_partial_results_empty_state_when_no_batches_completed(client):
    _make_suspended_run("autorun_partial_results_empty")
    # No result_store entry at all yet — 0 of N batches completed.
    res = client.get("/api/recon/auto-run/autorun_partial_results_empty/partial-results")
    assert res.status_code == 200
    body = res.json()
    assert body["batches"] == []
    assert body["batches_completed"] == 0


# ── run_registry state machine ──────────────────────────────────────────────

def test_suspended_is_not_active_and_not_terminal():
    assert RunState.SUSPENDED not in run_registry.ACTIVE_STATES
    assert RunState.SUSPENDED not in run_registry.TERMINAL_STATES
    assert RunState.SUSPENDED in run_registry.PARKED_STATES


def test_sweep_orphans_leaves_suspended_alone_but_fails_orphaned_suspending():
    pipeline_run_store.create("autorun_orphan_suspended")
    run_registry.transition("autorun_orphan_suspended", RunState.RUNNING, reason="test setup")
    run_registry.transition("autorun_orphan_suspended", RunState.SUSPENDING, reason="test setup")
    run_registry.transition("autorun_orphan_suspended", RunState.SUSPENDED, reason="test setup")

    pipeline_run_store.create("autorun_orphan_suspending")
    run_registry.transition("autorun_orphan_suspending", RunState.RUNNING, reason="test setup")
    run_registry.transition("autorun_orphan_suspending", RunState.SUSPENDING, reason="test setup")

    orphaned = run_registry.sweep_orphans()

    assert "autorun_orphan_suspended" not in orphaned
    assert run_registry.current_state("autorun_orphan_suspended") == RunState.SUSPENDED
    assert "autorun_orphan_suspending" in orphaned
    assert run_registry.current_state("autorun_orphan_suspending") == RunState.FAILED


# ── the underlying LangGraph mechanism: resuming after "suspended", not just
# "failed" — mirrors test_graph_retry_mechanism.py exactly, swapping in a
# cooperative "suspended" status returned mid-loop instead of a hard failure.

class _State(TypedDict, total=False):
    status: str
    calls: list[str]
    suspend_requested: bool


def _node_a(state: _State) -> dict:
    return {"calls": [*(state.get("calls") or []), "a"]}


def _node_b(state: _State) -> dict:
    calls = [*(state.get("calls") or []), "b"]
    if state.get("suspend_requested"):
        return {"calls": calls, "status": "suspended"}
    return {"calls": calls}


def _node_c(state: _State) -> dict:
    return {"calls": [*(state.get("calls") or []), "c"], "status": "completed"}


def _build(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "checkpoints.db"), check_same_thread=False)
    graph = StateGraph(_State)
    for name, fn in (("a", _node_a), ("b", _node_b), ("c", _node_c)):
        graph.add_node(name, fn)
    graph.add_edge(START, "a")
    for name, nxt in (("a", "b"), ("b", "c")):
        def _router(state, _next=nxt):
            return END if state.get("status") in ("failed", "suspended") else _next
        graph.add_conditional_edges(name, _router, [nxt, END])
    graph.add_edge("c", END)
    return graph.compile(checkpointer=SqliteSaver(conn))


def test_resume_after_suspended_status_reexecutes_only_the_named_nodes_successor(tmp_path):
    compiled = _build(tmp_path)
    config = {"configurable": {"thread_id": "run-suspend-1"}}

    result = compiled.invoke({"status": "running", "suspend_requested": True, "calls": []}, config=config)
    assert result["status"] == "suspended"
    assert result["calls"] == ["a", "b"]

    snapshot = compiled.get_state(config)
    assert not snapshot.interrupts  # a suspend is not a pending interrupt either

    values = dict(snapshot.values)
    values.update({"status": "running", "suspend_requested": False})
    compiled.update_state(config, values, as_node="a")

    result = compiled.invoke(None, config=config)

    # "b" and "c" re-ran; "a" was NOT re-executed.
    assert result["calls"] == ["a", "b", "b", "c"]
    assert result["status"] == "completed"
