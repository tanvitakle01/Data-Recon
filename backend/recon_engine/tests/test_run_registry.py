"""Coverage for the run-state machine's single chokepoint (see
``run_registry.transition``) — illegal edges are rejected, terminal states
stay terminal, and the orphan sweep only ever touches RUNNING/CANCELLING.
"""

from __future__ import annotations

import pytest

from backend.recon_engine import run_registry
from backend.recon_engine.run_registry import IllegalTransition, RunState
from backend.recon_engine.storage import pipeline_run_store


def _new_run(graph_run_id: str) -> None:
    pipeline_run_store.create(graph_run_id)


def test_created_run_can_start_running():
    _new_run("r1")
    run_registry.transition("r1", RunState.RUNNING, reason="start")
    assert run_registry.current_state("r1") == RunState.RUNNING


def test_illegal_transition_is_rejected_and_state_is_unchanged():
    _new_run("r2")
    run_registry.transition("r2", RunState.RUNNING, reason="start")
    with pytest.raises(IllegalTransition):
        run_registry.transition("r2", RunState.CREATED, reason="bogus")


def test_completed_is_terminal():
    _new_run("r3")
    run_registry.transition("r3", RunState.RUNNING, reason="start")
    run_registry.transition("r3", RunState.COMPLETED, reason="done")
    with pytest.raises(IllegalTransition):
        run_registry.transition("r3", RunState.RUNNING, reason="should not be allowed")


def test_cancelled_is_terminal():
    _new_run("r4")
    run_registry.transition("r4", RunState.RUNNING, reason="start")
    run_registry.transition("r4", RunState.CANCELLING, reason="user cancel")
    run_registry.transition("r4", RunState.CANCELLED, reason="cooperative cancel")
    with pytest.raises(IllegalTransition):
        run_registry.transition("r4", RunState.RUNNING, reason="should not be allowed")


def test_failed_run_can_retry_back_to_running():
    _new_run("r5")
    run_registry.transition("r5", RunState.RUNNING, reason="start")
    run_registry.transition("r5", RunState.FAILED, reason="batch failed")
    run_registry.transition("r5", RunState.RUNNING, reason="retry")
    assert run_registry.current_state("r5") == RunState.RUNNING


def test_stalled_run_can_still_complete():
    _new_run("r6")
    run_registry.transition("r6", RunState.RUNNING, reason="start")
    run_registry.transition("r6", RunState.STALLED, reason="heartbeat stale")
    run_registry.transition("r6", RunState.COMPLETED, reason="finished after recovering")
    assert run_registry.current_state("r6") == RunState.COMPLETED


def test_sweep_orphans_only_flips_running_and_cancelling():
    _new_run("orphan_running")
    run_registry.transition("orphan_running", RunState.RUNNING, reason="start")
    _new_run("orphan_cancelling")
    run_registry.transition("orphan_cancelling", RunState.RUNNING, reason="start")
    run_registry.transition("orphan_cancelling", RunState.CANCELLING, reason="user cancel")
    _new_run("not_orphaned")
    run_registry.transition("not_orphaned", RunState.RUNNING, reason="start")
    run_registry.transition("not_orphaned", RunState.COMPLETED, reason="done")

    flipped = set(run_registry.sweep_orphans())

    assert flipped == {"orphan_running", "orphan_cancelling"}
    assert run_registry.current_state("orphan_running") == RunState.FAILED
    assert run_registry.current_state("orphan_cancelling") == RunState.FAILED
    assert run_registry.current_state("not_orphaned") == RunState.COMPLETED


def test_format_failure_names_run_batch_and_node():
    message = run_registry.format_failure("autorun_ab12", "run_batches", batch_id="batch-7", detail="boom")
    assert "autorun_ab12" in message
    assert "run_batches" in message
    assert "batch-7" in message
    assert "boom" in message
