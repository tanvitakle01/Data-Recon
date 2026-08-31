"""``_do_finalize`` must only clear a run's batch plan/checkpoint (and
corroboration evidence) AFTER its own risky detail-frame read succeeds — never
before. Clearing first (the pre-fix ordering) left a run that hard-fails at
finalize with no resumable checkpoint at all, even though every batch had
already completed: ``routes.auto_pipeline._has_resumable_checkpoint`` would
then have nothing to point ``/retry`` at, and the Stored Runs progress badge
would misreport "0 batches completed" for a run that actually finished all of
them (see ``routes.auto_pipeline.list_stored_runs``/``get_partial_results``,
both of which read this same bookkeeping).
"""

from __future__ import annotations

import pytest

from backend.recon_engine.auto_pipeline import nodes
from backend.recon_engine.models.results import ReconciliationSummary
from backend.recon_engine.storage import pipeline_run_store, result_store


def _finalize_ready_state(graph_run_id: str) -> dict:
    pipeline_run_store.create(graph_run_id)
    pipeline_run_store.save_run_batch_plan(graph_run_id, [{"batch_index": i} for i in range(3)])
    result = result_store.start_streaming_result(run_id=graph_run_id, contract_id="c1", contract_version=1)
    pipeline_run_store.save_run_batch_checkpoint(
        graph_run_id, result_id=result.result_id, next_batch_index=3, batch_count=3,
        summary=ReconciliationSummary(total=0).model_dump(),
    )
    return {
        "graph_run_id": graph_run_id,
        "result_id": result.result_id,
        "contract_id": "c1",
        "contract_version": 1,
        "actor": "test",
    }


def test_a_failed_finalize_read_leaves_batch_state_intact(monkeypatch):
    graph_run_id = "autorun_finalize_ordering_fail"
    state = _finalize_ready_state(graph_run_id)

    def _boom(_result_id):
        raise ValueError("0 columns passed, passed data had 10 columns")

    monkeypatch.setattr(result_store, "load_result_frame_jsonl", _boom)

    with pytest.raises(ValueError):
        nodes._do_finalize(state)

    assert pipeline_run_store.get_run_batch_plan(graph_run_id) is not None
    assert pipeline_run_store.get_run_batch_checkpoint(graph_run_id) is not None


def test_a_successful_finalize_still_clears_batch_state(monkeypatch):
    graph_run_id = "autorun_finalize_ordering_ok"
    state = _finalize_ready_state(graph_run_id)

    result = nodes._do_finalize(state)

    assert result["status"] == "completed"
    assert pipeline_run_store.get_run_batch_plan(graph_run_id) is None
    assert pipeline_run_store.get_run_batch_checkpoint(graph_run_id) is None
