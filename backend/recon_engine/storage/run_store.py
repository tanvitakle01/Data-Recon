"""Reconciliation run store."""

from __future__ import annotations

import uuid

from backend.recon_engine.models.run import ReconciliationRun, RunStatus
from backend.recon_engine.storage.db import main_db


def new_run_id() -> str:
    return "run_" + uuid.uuid4().hex


def save_run(run: ReconciliationRun) -> ReconciliationRun:
    with main_db() as conn:
        conn.execute(
            """INSERT INTO runs
               (run_id, contract_id, contract_version, source_snapshot_id,
                target_snapshot_id, shadow_id, status, created_at, created_by, error)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                run.run_id, run.contract_id, run.contract_version, run.source_snapshot_id,
                run.target_snapshot_id, run.shadow_id, run.status.value,
                run.created_at.isoformat(), run.created_by, run.error,
            ),
        )
    return run


def update_run(run: ReconciliationRun) -> ReconciliationRun:
    with main_db() as conn:
        conn.execute(
            "UPDATE runs SET shadow_id=?, status=?, error=? WHERE run_id=?",
            (run.shadow_id, run.status.value, run.error, run.run_id),
        )
    return run


def _row_to_run(row) -> ReconciliationRun:
    return ReconciliationRun(
        run_id=row["run_id"],
        contract_id=row["contract_id"],
        contract_version=row["contract_version"],
        source_snapshot_id=row["source_snapshot_id"],
        target_snapshot_id=row["target_snapshot_id"],
        shadow_id=row["shadow_id"],
        status=RunStatus(row["status"]),
        created_at=row["created_at"],
        created_by=row["created_by"],
        error=row["error"],
    )


def get_run(run_id: str) -> ReconciliationRun | None:
    with main_db() as conn:
        row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    return _row_to_run(row) if row else None


def list_runs() -> list[ReconciliationRun]:
    with main_db() as conn:
        rows = conn.execute("SELECT * FROM runs ORDER BY created_at DESC").fetchall()
    return [_row_to_run(r) for r in rows]
