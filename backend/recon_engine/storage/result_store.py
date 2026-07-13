"""Reconciliation result store. Summary in SQLite, detail rows on disk."""

from __future__ import annotations

import json
import uuid

import pandas as pd

from backend.recon_engine.config import get_settings
from backend.recon_engine.models.results import ReconciliationResult, ReconciliationSummary
from backend.recon_engine.storage import frames
from backend.recon_engine.storage.db import main_db


def _new_id() -> str:
    return "result_" + uuid.uuid4().hex


def save_result(
    *,
    run_id: str,
    contract_id: str,
    contract_version: int,
    summary: ReconciliationSummary,
    detail_df: pd.DataFrame,
) -> ReconciliationResult:
    settings = get_settings()
    settings.ensure_dirs()

    result_id = _new_id()
    storage_path = str(settings.results_data_dir / f"{result_id}.json")
    frames.write_frame(detail_df, storage_path)

    result = ReconciliationResult(
        result_id=result_id,
        run_id=run_id,
        contract_id=contract_id,
        contract_version=contract_version,
        summary=summary,
        storage_path=storage_path,
    )

    with main_db() as conn:
        conn.execute(
            """INSERT INTO results
               (result_id, run_id, contract_id, contract_version, summary_json,
                storage_path, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (
                result.result_id, result.run_id, result.contract_id, result.contract_version,
                json.dumps(summary.model_dump()), result.storage_path,
                result.created_at.isoformat(),
            ),
        )
    return result


def _row_to_result(row) -> ReconciliationResult:
    return ReconciliationResult(
        result_id=row["result_id"],
        run_id=row["run_id"],
        contract_id=row["contract_id"],
        contract_version=row["contract_version"],
        summary=ReconciliationSummary.model_validate(json.loads(row["summary_json"])),
        storage_path=row["storage_path"],
        created_at=row["created_at"],
    )


def get_result(result_id: str) -> ReconciliationResult | None:
    with main_db() as conn:
        row = conn.execute(
            "SELECT * FROM results WHERE result_id = ?", (result_id,)
        ).fetchone()
    return _row_to_result(row) if row else None


def get_result_for_run(run_id: str) -> ReconciliationResult | None:
    with main_db() as conn:
        row = conn.execute(
            "SELECT * FROM results WHERE run_id = ? ORDER BY created_at DESC LIMIT 1",
            (run_id,),
        ).fetchone()
    return _row_to_result(row) if row else None


def load_result_frame(result_id: str) -> pd.DataFrame:
    result = get_result(result_id)
    if result is None:
        raise KeyError(f"Unknown result '{result_id}'.")
    return frames.read_frame(result.storage_path)
