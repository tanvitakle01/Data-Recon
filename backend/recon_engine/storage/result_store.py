"""Reconciliation result store (in-memory). Summary + detail rows both held
in process memory via ``storage.frames``."""

from __future__ import annotations

import uuid

import pandas as pd

from backend.recon_engine.models.results import ReconciliationResult, ReconciliationSummary
from backend.recon_engine.storage import frames

_RESULTS: dict[str, ReconciliationResult] = {}


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
    result_id = _new_id()
    storage_key = f"result:{result_id}"
    frames.write_frame(detail_df, storage_key)

    result = ReconciliationResult(
        result_id=result_id,
        run_id=run_id,
        contract_id=contract_id,
        contract_version=contract_version,
        summary=summary,
        storage_path=storage_key,
    )
    _RESULTS[result_id] = result
    return result


def start_streaming_result(
    *, run_id: str, contract_id: str, contract_version: int
) -> ReconciliationResult:
    """Creates the result record for a streaming run BEFORE any batch has
    processed — ``summary`` starts at all-zero and ``storage_path`` points at
    a key with no frame written yet (see ``storage.frames.append_frame``).
    Batch 1's call to :func:`append_batch_result` finds this row waiting and
    updates it in place; there is no separate "create" the caller needs to
    orchestrate around a first-batch special case.
    """
    result_id = _new_id()
    storage_key = f"result:{result_id}.jsonl"
    summary = ReconciliationSummary()

    result = ReconciliationResult(
        result_id=result_id,
        run_id=run_id,
        contract_id=contract_id,
        contract_version=contract_version,
        summary=summary,
        storage_path=storage_key,
    )
    _RESULTS[result_id] = result
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
    updated = result.model_copy(update={"summary": merged})
    _RESULTS[result_id] = updated
    return updated


def load_result_frame_jsonl(result_id: str) -> pd.DataFrame:
    """Loads a streaming result's detail rows (see :func:`start_streaming_result`
    / :func:`append_batch_result`) — the streaming counterpart to
    :func:`load_result_frame`."""
    result = get_result(result_id)
    if result is None:
        raise KeyError(f"Unknown result '{result_id}'.")
    return frames.read_frame_jsonl(result.storage_path)


def get_result(result_id: str) -> ReconciliationResult | None:
    return _RESULTS.get(result_id)


def get_result_for_run(run_id: str) -> ReconciliationResult | None:
    candidates = [r for r in _RESULTS.values() if r.run_id == run_id]
    if not candidates:
        return None
    return max(candidates, key=lambda r: r.created_at)


def load_result_frame(result_id: str) -> pd.DataFrame:
    result = get_result(result_id)
    if result is None:
        raise KeyError(f"Unknown result '{result_id}'.")
    return frames.read_frame(result.storage_path)


def load_result_frame_any(result_id: str) -> pd.DataFrame:
    """Loads a result's detail rows regardless of which writer produced them.

    A caller that only ever knows a bare ``result_id`` (e.g. a shared route or
    export builder reachable from both single-blob results and streaming
    results) can't pick :func:`load_result_frame` vs.
    :func:`load_result_frame_jsonl` up front — dispatches on ``storage_path``'s
    prefix instead, which is set once at creation (:func:`save_result` vs.
    :func:`start_streaming_result`) and never changes."""
    result = get_result(result_id)
    if result is None:
        raise KeyError(f"Unknown result '{result_id}'.")
    if result.storage_path.endswith(".jsonl"):
        return frames.read_frame_jsonl(result.storage_path)
    return frames.read_frame(result.storage_path)
