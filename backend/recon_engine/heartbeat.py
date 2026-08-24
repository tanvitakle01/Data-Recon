"""Liveness signal for a running Auto-mode node/batch.

``beat()`` is called from every top-level node (``auto_pipeline/nodes.py``'s
``_run_step``) and from the finer-grained ``run_batches``/``pair_values``
inner batch loops. The watchdog (``backend/main.py``'s startup task) flips any
run whose heartbeat has gone stale past the STALLED threshold — see
``run_registry.RunState.STALLED``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.recon_engine import run_registry
from backend.recon_engine.run_registry import RunState
from backend.recon_engine.storage.db import main_db

STALLED_THRESHOLD_SECONDS = 60


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def beat(run_id: str, *, node: str, batch_id: str | None = None) -> None:
    with main_db() as conn:
        conn.execute(
            """INSERT INTO run_heartbeats (run_id, batch_id, node, updated_at)
               VALUES (?,?,?,?)
               ON CONFLICT (run_id) DO UPDATE SET
                   batch_id = excluded.batch_id,
                   node = excluded.node,
                   updated_at = excluded.updated_at""",
            (run_id, batch_id, node, _now()),
        )
    # A heartbeat arriving for a run the watchdog had marked STALLED means the
    # node/batch that looked stuck is actually still making progress — recover
    # it back to RUNNING rather than leaving a stale "stalled" label to fade
    # on its own only once the node finally completes.
    if run_registry.current_state(run_id) == RunState.STALLED:
        run_registry.transition(run_id, RunState.RUNNING, reason="heartbeat resumed")


def sweep_stalled(threshold_seconds: int = STALLED_THRESHOLD_SECONDS) -> list[str]:
    """Flip any RUNNING run whose heartbeat is older than ``threshold_seconds``
    (or has none at all — a run past its first node should always have one) to
    STALLED. Returns the run_ids flipped. CANCELLING is deliberately excluded
    — it has no legal STALLED transition (see ``run_registry._TRANSITIONS``):
    a cancel is expected to resolve quickly via the next cooperative
    checkpoint, not sit long enough to look "stalled" in its own right."""
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=threshold_seconds)).isoformat()
    with main_db() as conn:
        rows = conn.execute(
            """SELECT pr.graph_run_id AS run_id
               FROM pipeline_runs pr
               LEFT JOIN run_heartbeats hb ON hb.run_id = pr.graph_run_id
               WHERE pr.status = ?
                 AND (hb.updated_at IS NULL OR hb.updated_at < ?)""",
            (RunState.RUNNING.value, cutoff),
        ).fetchall()
    stalled: list[str] = []
    for row in rows:
        run_registry.transition(row["run_id"], RunState.STALLED, reason="heartbeat stale")
        stalled.append(row["run_id"])
    return stalled
