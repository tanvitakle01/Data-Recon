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


def start_streaming_result(
    *, run_id: str, contract_id: str, contract_version: int
) -> ReconciliationResult:
    """Creates the ``results`` row for a streaming run BEFORE any batch has
    processed — ``summary`` starts at all-zero and ``storage_path`` points at
    a JSON-Lines file (see ``storage.frames.append_frame``) that doesn't exist
    yet. Batch 1's call to :func:`append_batch_result` finds this row waiting
    and updates it in place; there is no separate "create" the caller needs to
    orchestrate around a first-batch special case.
    """
    settings = get_settings()
    settings.ensure_dirs()

    result_id = _new_id()
    storage_path = str(settings.results_data_dir / f"{result_id}.jsonl")
    summary = ReconciliationSummary()

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


def append_batch_result(
    result_id: str, *, detail_df: pd.DataFrame, batch_summary: ReconciliationSummary
) -> ReconciliationResult:
    """Appends one batch's detail rows and rolls ``batch_summary`` into the
    running total — called once per completed batch so a run interrupted
    partway through still has valid, inspectable results for every batch
    completed so far (no separate "finalize" step needed to make partial
    results visible)."""
    result = get_result(result_id)
    if result is None:
        raise KeyError(f"Unknown result {result_id!r}.")

    frames.append_frame(detail_df, result.storage_path)

    all_fields = set(result.summary.excluded_unmapped) | set(batch_summary.excluded_unmapped)
    merged = ReconciliationSummary(
        total=result.summary.total + batch_summary.total,
        match=result.summary.match + batch_summary.match,
        quantity_mismatch=result.summary.quantity_mismatch + batch_summary.quantity_mismatch,
        missing_in_target=result.summary.missing_in_target + batch_summary.missing_in_target,
        extra_in_target=result.summary.extra_in_target + batch_summary.extra_in_target,
        mismatch=result.summary.mismatch + batch_summary.mismatch,
        excluded_unmapped={
            field: (
                result.summary.excluded_unmapped.get(field, 0)
                + batch_summary.excluded_unmapped.get(field, 0)
            )
            for field in all_fields
        },
    )
    with main_db() as conn:
        conn.execute(
            "UPDATE results SET summary_json = ? WHERE result_id = ?",
            (json.dumps(merged.model_dump()), result_id),
        )
    return result.model_copy(update={"summary": merged})


def load_result_frame_jsonl(result_id: str) -> pd.DataFrame:
    """Loads a streaming result's detail rows (see :func:`start_streaming_result`
    / :func:`append_batch_result`) — the JSON-Lines counterpart to
    :func:`load_result_frame`."""
    result = get_result(result_id)
    if result is None:
        raise KeyError(f"Unknown result '{result_id}'.")
    return frames.read_frame_jsonl(result.storage_path)


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


def load_result_frame_any(result_id: str) -> pd.DataFrame:
    """Loads a result's detail rows regardless of which writer produced them.

    A caller that only ever knows a bare ``result_id`` (e.g. a shared route or
    export builder reachable from both Manual mode's single-blob results and
    Auto-mode's streaming ``.jsonl`` results) can't pick :func:`load_result_frame`
    vs. :func:`load_result_frame_jsonl` up front — dispatches on
    ``storage_path``'s extension instead, which is set once at creation
    (:func:`save_result` vs. :func:`start_streaming_result`) and never changes."""
    result = get_result(result_id)
    if result is None:
        raise KeyError(f"Unknown result '{result_id}'.")
    if result.storage_path.endswith(".jsonl"):
        return frames.read_frame_jsonl(result.storage_path)
    return frames.read_frame(result.storage_path)
