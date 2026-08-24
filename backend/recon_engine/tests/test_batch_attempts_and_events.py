"""New traceability stores backing the UUID identity layer:

* ``pipeline_run_store.record_batch_attempt``/``get_latest_batch_attempt`` —
  the per-attempt audit trail a retried batch chains onto via
  ``supersedes_batch_id`` (see ``auto_pipeline/nodes.py::_do_run_batches``).
* ``error_event_store`` — one row per hard node failure.
* ``llm_call_store`` — one row per ``FailoverLLMClient.complete_json`` call.
"""

from __future__ import annotations

from backend.recon_engine.llm.call_context import (
    clear_llm_call_context,
    get_llm_call_context,
    set_llm_call_context,
)
from backend.recon_engine.storage import error_event_store, llm_call_store, pipeline_run_store
from backend.recon_engine.storage.db import main_db


def test_get_latest_batch_attempt_none_when_never_attempted():
    assert pipeline_run_store.get_latest_batch_attempt("run-1", 0) is None


def test_record_and_retrieve_batch_attempt():
    pipeline_run_store.record_batch_attempt(
        "run-1", batch_id="b1", batch_index=0, supersedes_batch_id=None, status="completed"
    )
    latest = pipeline_run_store.get_latest_batch_attempt("run-1", 0)
    assert latest["batch_id"] == "b1"
    assert latest["status"] == "completed"
    assert latest["supersedes_batch_id"] is None


def test_a_retried_attempt_chains_via_supersedes_and_never_overwrites_the_failed_one():
    pipeline_run_store.record_batch_attempt(
        "run-1", batch_id="b1", batch_index=0, supersedes_batch_id=None,
        status="failed", error="connector timeout",
    )
    prior = pipeline_run_store.get_latest_batch_attempt("run-1", 0)
    assert prior["batch_id"] == "b1"

    pipeline_run_store.record_batch_attempt(
        "run-1", batch_id="b2", batch_index=0, supersedes_batch_id=prior["batch_id"],
        status="completed",
    )
    latest = pipeline_run_store.get_latest_batch_attempt("run-1", 0)
    assert latest["batch_id"] == "b2"
    assert latest["supersedes_batch_id"] == "b1"

    # The failed attempt's row is still there (not overwritten), audit-visible.
    with main_db() as conn:
        rows = conn.execute(
            "SELECT batch_id, status FROM run_batch_attempts WHERE run_id = ? ORDER BY created_at",
            ("run-1",),
        ).fetchall()
    assert [dict(r) for r in rows] == [
        {"batch_id": "b1", "status": "failed"},
        {"batch_id": "b2", "status": "completed"},
    ]


def test_batch_attempts_are_scoped_per_run():
    pipeline_run_store.record_batch_attempt(
        "run-1", batch_id="b1", batch_index=0, supersedes_batch_id=None, status="completed"
    )
    assert pipeline_run_store.get_latest_batch_attempt("run-2", 0) is None


def test_error_event_store_records_and_lists_by_run():
    event_id = error_event_store.record(run_id="run-1", batch_id=None, node="resolve_schema", message="boom")
    assert event_id
    events = error_event_store.list_for_run("run-1")
    assert len(events) == 1
    assert events[0]["node"] == "resolve_schema"
    assert events[0]["message"] == "boom"
    assert events[0]["batch_id"] is None


def test_error_event_store_get_by_id():
    event_id = error_event_store.record(run_id="run-1", batch_id="b1", node="run_batches", message="fetch failed")
    got = error_event_store.get(event_id)
    assert got["error_event_id"] == event_id
    assert got["batch_id"] == "b1"


def test_llm_call_context_defaults_to_all_none():
    clear_llm_call_context()
    ctx = get_llm_call_context()
    assert ctx.run_id is None
    assert ctx.batch_id is None
    assert ctx.node is None


def test_llm_call_store_records_context_from_contextvar():
    set_llm_call_context(run_id="run-1", batch_id="b1", node="run_batches")
    llm_call_store.record(
        run_id=get_llm_call_context().run_id,
        batch_id=get_llm_call_context().batch_id,
        node=get_llm_call_context().node,
        preferred="groq",
        provider_used="groq",
        fallback_occurred=False,
        all_failed=False,
    )
    calls = llm_call_store.list_for_run("run-1")
    assert len(calls) == 1
    assert calls[0]["batch_id"] == "b1"
    assert calls[0]["provider_used"] == "groq"
    clear_llm_call_context()


def test_llm_call_store_allows_null_context_for_non_run_callers():
    call_id = llm_call_store.record(
        run_id=None, batch_id=None, node=None,
        preferred="groq", provider_used=None, fallback_occurred=False, all_failed=True,
    )
    assert call_id
