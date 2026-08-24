"""Run-state machine — the single chokepoint for changing an Auto-mode run's
lifecycle status.

INVARIANT: ``pipeline_runs.status`` is never written anywhere except inside
:func:`transition`. Every other module that used to write it directly
(``routes/auto_pipeline.py``, ``auto_pipeline/nodes.py``) now calls
:func:`transition` for the status change and
``storage.pipeline_run_store.update_progress`` (which has no ``status``
parameter at all) for everything else — a status change literally cannot
happen through any other code path.

States: CREATED, RUNNING, PAUSED_FOR_INPUT, CANCELLING, STALLED, and terminal
COMPLETED / CANCELLED. FAILED is deliberately NOT fully terminal here — this
codebase's batch-checkpointed run_batches/pair_values steps make a "failed"
run resumable (see routes/auto_pipeline.py's ``/retry``), so FAILED's only
legal outgoing edge is back to RUNNING (a retry), never anything else.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Callable

from backend.recon_engine.storage.db import main_db


class RunState(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED_FOR_INPUT = "waiting_for_input"  # existing on-disk/frontend string, kept unchanged
    CANCELLING = "cancelling"
    STALLED = "stalled"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# States a NEW_RUN confirmation / orphan sweep / watchdog must treat as "still
# doing something" — deliberately excludes FAILED (a failed run doesn't block
# a fresh one; the user did not ask for it to be retried) and the terminal set.
ACTIVE_STATES = {RunState.RUNNING, RunState.PAUSED_FOR_INPUT, RunState.CANCELLING, RunState.STALLED}

TERMINAL_STATES = {RunState.COMPLETED, RunState.CANCELLED}

_TRANSITIONS: dict[RunState, set[RunState]] = {
    RunState.CREATED: {RunState.RUNNING, RunState.CANCELLED},
    RunState.RUNNING: {
        RunState.PAUSED_FOR_INPUT,
        RunState.CANCELLING,
        RunState.STALLED,
        RunState.COMPLETED,
        RunState.FAILED,
    },
    RunState.PAUSED_FOR_INPUT: {RunState.RUNNING, RunState.CANCELLING, RunState.FAILED},
    RunState.STALLED: {
        RunState.RUNNING,
        RunState.CANCELLING,
        RunState.FAILED,
        RunState.COMPLETED,
        RunState.PAUSED_FOR_INPUT,
    },
    RunState.CANCELLING: {RunState.CANCELLED, RunState.FAILED},
    RunState.FAILED: {RunState.RUNNING},  # retry only
}


class IllegalTransition(Exception):
    """Raised when a requested transition isn't legal from the run's current state."""


class CooperativeCancellation(Exception):
    """Raised from inside a running node/batch loop to unwind cooperatively once
    ``is_cancelling`` is observed true — caught in ``nodes.py``'s ``_run_step``
    and turned into a ``status: "cancelled"`` node update, never a hard failure."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def current_state(run_id: str) -> RunState:
    with main_db() as conn:
        row = conn.execute("SELECT status FROM pipeline_runs WHERE graph_run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise ValueError(f"Unknown run {run_id!r} — cannot read its state.")
    return RunState(row["status"])


def is_cancelling(run_id: str) -> bool:
    return current_state(run_id) == RunState.CANCELLING


def is_active(run_id: str) -> bool:
    return current_state(run_id) in ACTIVE_STATES


def transition(run_id: str, to_state: RunState, *, reason: str) -> None:
    """The ONE function allowed to change ``pipeline_runs.status`` — validates
    the edge against ``_TRANSITIONS``, writes the new status, and appends one
    row to ``run_transitions`` (audit trail), all in a single transaction."""
    with main_db() as conn:
        row = conn.execute("SELECT status FROM pipeline_runs WHERE graph_run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown run {run_id!r} — cannot transition it.")
        current = RunState(row["status"])
        legal = _TRANSITIONS.get(current, set())
        if to_state not in legal:
            raise IllegalTransition(
                f"Run {run_id!r}: illegal transition {current.value!r} -> {to_state.value!r} "
                f"(reason: {reason!r}). Legal targets from {current.value!r}: "
                f"{sorted(s.value for s in legal) or 'none (terminal)'}."
            )
        conn.execute(
            "UPDATE pipeline_runs SET status = ? WHERE graph_run_id = ?", (to_state.value, run_id)
        )
        conn.execute(
            """INSERT INTO run_transitions (run_id, from_state, to_state, reason, created_at)
               VALUES (?,?,?,?,?)""",
            (run_id, current.value, to_state.value, reason, _now()),
        )


def sweep_orphans() -> list[str]:
    """Boot-time recovery: any run left in RUNNING/CANCELLING when the process
    last stopped can only mean the process died mid-run — flip it to FAILED
    (reason ``process_terminated``) so it can never again look like a live,
    blocking, active run. PAUSED_FOR_INPUT is deliberately left alone: it is
    durably resumable via LangGraph's own SqliteSaver checkpoint across a
    restart, so orphaning it here would destroy a perfectly resumable run.
    """
    orphaned: list[str] = []
    with main_db() as conn:
        rows = conn.execute(
            "SELECT graph_run_id FROM pipeline_runs WHERE status IN (?, ?)",
            (RunState.RUNNING.value, RunState.CANCELLING.value),
        ).fetchall()
    for row in rows:
        run_id = row["graph_run_id"]
        transition(run_id, RunState.FAILED, reason="process_terminated")
        orphaned.append(run_id)
    return orphaned


def format_failure(run_id: str, node: str, *, batch_id: str | None = None, detail: str) -> str:
    """Every failure message surfaced to the user must name run_id/batch_id/
    node explicitly as literal text, never rely solely on structured columns
    (see error_event_store, which already carries them separately)."""
    where = f"node '{node}'" + (f", batch '{batch_id}'" if batch_id else "")
    return f"Run {run_id} failed at {where}: {detail}"


def transition_or_raise_cancelled(run_id: str) -> None:
    """Call at a cooperative-cancellation checkpoint (top of a node, top of a
    batch-loop iteration): raises :class:`CooperativeCancellation` if the run
    has been asked to cancel, so the caller unwinds immediately rather than
    doing another node's/batch's worth of work first."""
    if is_cancelling(run_id):
        raise CooperativeCancellation(run_id)
