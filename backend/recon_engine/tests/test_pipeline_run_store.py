"""Coverage for the Auto-mode pipeline run store's batch-checkpoint
primitives — what lets a hard-failed pair_values step be retried from exactly
the batch it stopped at (see auto_pipeline/nodes.py's _make_batch_progress_cb
and auto_pipeline/graph.py's retry_auto_pipeline).
"""

from __future__ import annotations

from backend.recon_engine.storage import pipeline_run_store


def test_batch_checkpoint_round_trips_and_upserts():
    graph_run_id = "autorun_checkpoint_test"
    pipeline_run_store.create(graph_run_id)

    assert pipeline_run_store.get_batch_checkpoint(graph_run_id, "Material -> PRDID") is None
    assert pipeline_run_store.has_batch_checkpoints(graph_run_id) is False

    pipeline_run_store.save_batch_checkpoint(
        graph_run_id,
        field_pair="Material -> PRDID",
        next_batch_index=1,
        batch_count=3,
        matches=[{"source_value": "A", "target_value": "A"}],
    )
    checkpoint = pipeline_run_store.get_batch_checkpoint(graph_run_id, "Material -> PRDID")
    assert checkpoint == {
        "next_batch_index": 1,
        "batch_count": 3,
        "matches": [{"source_value": "A", "target_value": "A"}],
    }
    assert pipeline_run_store.has_batch_checkpoints(graph_run_id) is True

    # A second write for the SAME field pair upserts rather than duplicating.
    pipeline_run_store.save_batch_checkpoint(
        graph_run_id,
        field_pair="Material -> PRDID",
        next_batch_index=2,
        batch_count=3,
        matches=[
            {"source_value": "A", "target_value": "A"},
            {"source_value": "B", "target_value": "B"},
        ],
    )
    checkpoint = pipeline_run_store.get_batch_checkpoint(graph_run_id, "Material -> PRDID")
    assert checkpoint["next_batch_index"] == 2
    assert len(checkpoint["matches"]) == 2

    # A different field pair on the SAME run gets its own independent row.
    pipeline_run_store.save_batch_checkpoint(
        graph_run_id,
        field_pair="Plant -> LOCID",
        next_batch_index=1,
        batch_count=1,
        matches=[],
    )
    assert pipeline_run_store.get_batch_checkpoint(graph_run_id, "Material -> PRDID")["next_batch_index"] == 2
    assert pipeline_run_store.get_batch_checkpoint(graph_run_id, "Plant -> LOCID")["next_batch_index"] == 1

    pipeline_run_store.clear_batch_checkpoints(graph_run_id)
    assert pipeline_run_store.get_batch_checkpoint(graph_run_id, "Material -> PRDID") is None
    assert pipeline_run_store.get_batch_checkpoint(graph_run_id, "Plant -> LOCID") is None
    assert pipeline_run_store.has_batch_checkpoints(graph_run_id) is False
