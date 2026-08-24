"""Auto-mode pipeline API: start a run, poll its status.

No job/polling infrastructure exists elsewhere in this codebase — every other
route here runs its business logic synchronously inline within one request.
This is the deliberate exception: Auto mode's 7-step run needs to be
observable mid-flight (elapsed time, current step) rather than blocking one
HTTP request for however long a live SAP/IBP fetch + LLM pairing +
reconciliation takes.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from pydantic import BaseModel, Field

from backend.excel_comparator.core.loader import load_tabular
from backend.recon_engine import run_registry, service
from backend.recon_engine.auto_pipeline.graph import (
    get_pending_interrupt,
    resume_auto_pipeline,
    retry_auto_pipeline,
    stream_auto_pipeline,
)
from backend.recon_engine.auto_pipeline.graph_from_data import (
    get_pending_interrupt_from_data,
    resume_auto_pipeline_from_data,
    retry_auto_pipeline_from_data,
    stream_auto_pipeline_from_data,
)
from backend.recon_engine.auto_pipeline.state import AutoRunState
from backend.recon_engine.models.snapshot import RawLayer
from backend.recon_engine.run_registry import RunState
from backend.recon_engine.storage import pipeline_run_store

router = APIRouter(prefix="/api/recon/auto-run", tags=["recon-auto-pipeline"])

# Keeps a strong reference to in-flight background tasks — asyncio does not
# guarantee a task survives if nothing else holds it, and the request that
# created it returns immediately.
_background_tasks: set[asyncio.Task] = set()

# Distinguishes a "from-data" run (chat-uploaded files, entering the graph at
# identify_candidate_keys — see graph_from_data.py) from a normal full-graph
# run, purely by id prefix — avoids a pipeline_runs schema migration just to
# record which of the two compiled graphs owns a given run.
_FROM_DATA_PREFIX = "autorun_fd_"


def _is_from_data(graph_run_id: str) -> bool:
    return graph_run_id.startswith(_FROM_DATA_PREFIX)


class AutoRunStartRequest(BaseModel):
    mapping_sheet: Any = Field(default_factory=dict)
    identification: dict[str, Any]
    comparison_type: str | None = None
    actor: str = "auto"


class AutoRunResolveRequest(BaseModel):
    # A chip tap and free text both land here as a plain string — the
    # interrupted node re-validates it against live options either way (see
    # interrupts.py), so there is nothing for the route itself to validate.
    value: str


def _partial_result(state: AutoRunState) -> dict[str, Any]:
    """Whatever of the run's output is available so far — not gated on
    completion. Polled after every step so the frontend can apply each
    piece (source dataset, target dataset, value mappings, ...) to wizard
    state as soon as it exists, per the incremental-sync design: if Auto
    hard-stops partway through, whatever already succeeded stays usable in
    Manual mode instead of being discarded.
    """
    return {
        "contract_id": state.get("contract_id"),
        "contract_version": state.get("contract_version"),
        "run_id": state.get("run_id"),
        "result_summary": state.get("result_summary"),
        "source": state.get("source"),
        "target": state.get("target"),
        "product_mapping": state.get("product_mapping"),
        "location_mapping": state.get("location_mapping"),
    }


def _on_step(graph_run_id: str, step_name: str, state: AutoRunState) -> None:
    # Progress only — NEVER status. A node that just hard-failed or requested
    # cancellation still reports its step/timestamps/partial result here, but
    # the actual status change (if any) is decided once, authoritatively, by
    # _finish below — writing it here too would let this callback and _finish
    # race to transition the same run twice for one outcome (e.g. both trying
    # to move a run into FAILED, the second attempt illegal since FAILED is
    # terminal-for-that-edge). See run_registry.transition's docstring.
    pipeline_run_store.update_progress(
        graph_run_id,
        current_step=step_name,
        step_timestamps=state.get("step_timestamps") or {},
        failed_step=state.get("failed_step"),
        error=state.get("error"),
        result=_partial_result(state),
        # Mid-run — never paused at this point (a pause stops the stream
        # loop before this callback fires again), so any earlier pending
        # question is stale and must not linger.
        interrupt=None,
    )


def _finish(graph_run_id: str, final_state: AutoRunState) -> None:
    """Record a stream's outcome: completed, hard-failed, cooperatively
    cancelled, or RECOVERABLY paused waiting on the resolver bot's next
    answer — the ONE place that decides the run's terminal-for-this-stream
    status and transitions it via run_registry.

    A pause never returns a "completed"/"failed" status from the stream
    itself (the interrupting node raised instead of returning) — checked via
    the owning graph's own checkpoint (full graph vs. from-data graph,
    dispatched by id prefix), the single source of truth for whether a
    thread is actually waiting.
    """
    pending = (
        get_pending_interrupt_from_data(graph_run_id)
        if _is_from_data(graph_run_id)
        else get_pending_interrupt(graph_run_id)
    )
    if pending is not None:
        run_registry.transition(graph_run_id, RunState.PAUSED_FOR_INPUT, reason="node interrupted, awaiting input")
        pipeline_run_store.update_progress(
            graph_run_id,
            step_timestamps=final_state.get("step_timestamps") or {},
            failed_step=None,
            error=None,
            result=_partial_result(final_state),
            interrupt=pending,
        )
        return

    node_status = final_state.get("status", "failed")
    to_state = {
        "completed": RunState.COMPLETED,
        "cancelled": RunState.CANCELLED,
    }.get(node_status, RunState.FAILED)
    reason = final_state.get("error") or f"node status={node_status!r}"
    run_registry.transition(graph_run_id, to_state, reason=reason)
    pipeline_run_store.update_progress(
        graph_run_id,
        step_timestamps=final_state.get("step_timestamps") or {},
        failed_step=final_state.get("failed_step"),
        error=final_state.get("error"),
        result=_partial_result(final_state),
        interrupt=None,
    )


def _fail_hard(graph_run_id: str, exc: Exception) -> None:
    """A bug in the graph invocation itself (not a modeled node failure —
    those are caught and turned into a "failed" node status inside
    ``nodes.py``'s ``_run_step``, handled by ``_finish`` above instead)."""
    message = run_registry.format_failure(graph_run_id, "graph", detail=str(exc))
    run_registry.transition(graph_run_id, RunState.FAILED, reason=message)
    pipeline_run_store.update_progress(graph_run_id, error=message, interrupt=None)


def _execute(graph_run_id: str, initial_state: AutoRunState) -> None:
    stream_fn = stream_auto_pipeline_from_data if _is_from_data(graph_run_id) else stream_auto_pipeline
    try:
        final_state = stream_fn(initial_state, on_step=lambda step, s: _on_step(graph_run_id, step, s))
    except Exception as exc:  # noqa: BLE001 - a bug in the graph itself, not a modeled step failure
        _fail_hard(graph_run_id, exc)
        return
    _finish(graph_run_id, final_state)


def _execute_resume(graph_run_id: str, resume_value: str) -> None:
    resume_fn = resume_auto_pipeline_from_data if _is_from_data(graph_run_id) else resume_auto_pipeline
    try:
        final_state = resume_fn(
            graph_run_id, resume_value, on_step=lambda step, s: _on_step(graph_run_id, step, s)
        )
    except Exception as exc:  # noqa: BLE001 - a bug in the graph itself, not a modeled step failure
        _fail_hard(graph_run_id, exc)
        return
    _finish(graph_run_id, final_state)


def _execute_retry(graph_run_id: str) -> None:
    retry_fn = retry_auto_pipeline_from_data if _is_from_data(graph_run_id) else retry_auto_pipeline
    try:
        final_state = retry_fn(graph_run_id, on_step=lambda step, s: _on_step(graph_run_id, step, s))
    except Exception as exc:  # noqa: BLE001 - a bug in the graph itself, not a modeled step failure
        _fail_hard(graph_run_id, exc)
        return
    _finish(graph_run_id, final_state)


async def _run_in_background(graph_run_id: str, initial_state: AutoRunState) -> None:
    await asyncio.to_thread(_execute, graph_run_id, initial_state)


async def _resume_in_background(graph_run_id: str, resume_value: str) -> None:
    await asyncio.to_thread(_execute_resume, graph_run_id, resume_value)


async def _retry_in_background(graph_run_id: str) -> None:
    await asyncio.to_thread(_execute_retry, graph_run_id)


def start_auto_run_state(initial_state: dict[str, Any]) -> str:
    """Shared by the ``/start`` route and the chat orchestrator — both build
    an ``AutoRunState`` dict, this function owns creating the run record and
    kicking off the background execution either way."""
    graph_run_id = initial_state["graph_run_id"]
    pipeline_run_store.create(graph_run_id)
    run_registry.transition(graph_run_id, RunState.RUNNING, reason="run started")
    task = asyncio.create_task(_run_in_background(graph_run_id, initial_state))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return graph_run_id


def start_auto_run_from_data_state(
    *,
    source_df,
    target_df,
    source_name: str,
    target_name: str,
    comparison_type: str | None = None,
    actor: str = "auto",
) -> str:
    """Ingests two already-loaded DataFrames as snapshots and starts the
    from-data graph (identify_candidate_keys onwards) — shared by the
    ``/start-from-data`` route and the chat orchestrator."""
    graph_run_id = _FROM_DATA_PREFIX + uuid4().hex

    source_snap = service.ingest_snapshot(
        source_df, layer=RawLayer.SOURCE, source_type="upload",
        comparison_type=comparison_type, created_by=actor,
        lineage={"graph_run_id": graph_run_id, "filename": source_name},
    )
    target_snap = service.ingest_snapshot(
        target_df, layer=RawLayer.TARGET, source_type="upload",
        comparison_type=comparison_type, created_by=actor,
        lineage={"graph_run_id": graph_run_id, "filename": target_name},
    )

    initial_state: AutoRunState = {
        "graph_run_id": graph_run_id,
        "actor": actor,
        "comparison_type": comparison_type,
        "mapping_sheet": None,
        "source": {
            "kind": "upload",
            "connector_id": None,
            "primary_entity": source_name,
            "fields": list(source_snap.columns),
            "entities": [],
            "join_type": None,
            "join_keys": [],
            "snapshot_id": source_snap.snapshot_id,
            "row_count": source_snap.row_count,
            "columns": list(source_snap.columns),
        },
        "target": {
            "kind": "upload",
            "connector_id": None,
            "primary_entity": target_name,
            "fields": list(target_snap.columns),
            "entities": [],
            "join_type": None,
            "join_keys": [],
            "snapshot_id": target_snap.snapshot_id,
            "row_count": target_snap.row_count,
            "columns": list(target_snap.columns),
        },
    }
    return start_auto_run_state(initial_state)


@router.post("/start")
async def start_auto_run(req: AutoRunStartRequest) -> dict[str, Any]:
    graph_run_id = pipeline_run_store.new_graph_run_id()
    initial_state: AutoRunState = {
        "graph_run_id": graph_run_id,
        "actor": req.actor,
        "comparison_type": req.comparison_type,
        "mapping_sheet": req.mapping_sheet,
        "identification": req.identification,
    }
    start_auto_run_state(initial_state)
    return {"graph_run_id": graph_run_id}


@router.post("/start-from-data")
async def start_auto_run_from_data(
    source_file: UploadFile = File(...),
    target_file: UploadFile = File(...),
    comparison_type: str | None = Form(None),
    actor: str = Form("auto"),
) -> dict[str, Any]:
    """Chat/quick-reconcile entry point: two uploaded files, no mapping sheet,
    no live connector — enters the Auto-mode graph from identify_candidate_keys
    onwards (see graph_from_data.py) instead of the full 8-node graph."""
    source_bytes = await source_file.read()
    target_bytes = await target_file.read()
    if not source_bytes or not target_bytes:
        raise HTTPException(status_code=400, detail="Both source_file and target_file are required.")

    source_df = load_tabular(source_bytes, source_file.filename or "source.csv")
    target_df = load_tabular(target_bytes, target_file.filename or "target.csv")

    graph_run_id = start_auto_run_from_data_state(
        source_df=source_df,
        target_df=target_df,
        source_name=source_file.filename or "source",
        target_name=target_file.filename or "target",
        comparison_type=comparison_type,
        actor=actor,
    )
    return {"graph_run_id": graph_run_id}


def _has_resumable_checkpoint(graph_run_id: str, failed_step: str | None) -> bool:
    """Which checkpoint mechanism applies depends on which of the two
    compiled graphs owns this run (see ``_is_from_data``): the from-data
    graph still batches only inside ``pair_values`` (year-window batches, one
    checkpoint per field pair — see ``pipeline_run_store.
    has_batch_checkpoints``); the live-connector graph batches the WHOLE
    extract+pair+reconcile sequence inside ``run_batches`` (one checkpoint per
    run — see ``pipeline_run_store.has_run_batch_checkpoint``)."""
    if _is_from_data(graph_run_id):
        return failed_step == "pair_values" and pipeline_run_store.has_batch_checkpoints(graph_run_id)
    return failed_step == "run_batches" and pipeline_run_store.has_run_batch_checkpoint(graph_run_id)


def has_resumable_checkpoint(graph_run_id: str) -> bool:
    """Public form of :func:`_has_resumable_checkpoint` — used by the chat
    orchestrator's RETRY intent (``chat_assistant/orchestrator.py``) to answer
    "is there anything to retry" without duplicating the HTTP route's guard."""
    run = pipeline_run_store.get(graph_run_id)
    if run is None or run.get("status") != "failed":
        return False
    return _has_resumable_checkpoint(graph_run_id, run.get("failed_step"))


def trigger_retry(graph_run_id: str, *, reason: str = "retry") -> None:
    """Flips a resumable-failed run back to RUNNING and kicks off the retry in
    the background — the exact side effect ``POST /{id}/retry`` performs,
    factored out so the chat orchestrator's RETRY intent can trigger the same
    thing without going through HTTP. Caller must have already confirmed
    :func:`has_resumable_checkpoint`."""
    run = pipeline_run_store.get(graph_run_id)
    run_registry.transition(graph_run_id, RunState.RUNNING, reason=reason)
    pipeline_run_store.update_progress(
        graph_run_id,
        current_step=run.get("current_step") if run else None,
        step_timestamps=(run or {}).get("step_timestamps") or {},
        result=(run or {}).get("result"),
        interrupt=None,
    )
    task = asyncio.create_task(_retry_in_background(graph_run_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


@router.get("/{graph_run_id}/status")
def get_auto_run_status(graph_run_id: str) -> dict[str, Any]:
    run = pipeline_run_store.get(graph_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Unknown auto-run '{graph_run_id}'.")
    # A batch-level interruption is retryable ONLY when it failed inside the
    # one step with a batch concept AND at least one batch actually resolved
    # before the failure — otherwise there's nothing to resume from and the
    # frontend falls back to the plain generic error.
    run["resumable"] = (
        run.get("status") == "failed"
        and _has_resumable_checkpoint(graph_run_id, run.get("failed_step"))
    )
    return run


@router.post("/{graph_run_id}/resolve")
async def resolve_auto_run(graph_run_id: str, req: AutoRunResolveRequest) -> dict[str, Any]:
    """Answer the resolver bot's pending question (a chip tap or free text)
    and resume the run from exactly the node that paused it.

    Never restarts the run: :func:`resume_auto_pipeline` resumes the
    checkpointed graph via ``Command(resume=...)``, and the interrupted node
    re-validates this value against the same live options it already fetched
    — an invalid answer pauses again (status flips back to
    ``waiting_for_input`` with fresh chips) rather than being accepted or
    failing the run.
    """
    run = pipeline_run_store.get(graph_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Unknown auto-run '{graph_run_id}'.")
    if run.get("status") != "waiting_for_input":
        raise HTTPException(
            status_code=409,
            detail=f"Auto-run '{graph_run_id}' is not waiting for input (status={run.get('status')!r}).",
        )

    run_registry.transition(graph_run_id, RunState.RUNNING, reason="resolve")
    pipeline_run_store.update_progress(
        graph_run_id,
        current_step=run.get("current_step"),
        step_timestamps=run.get("step_timestamps") or {},
        result=run.get("result"),
        interrupt=None,
    )
    task = asyncio.create_task(_resume_in_background(graph_run_id, req.value))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return {"graph_run_id": graph_run_id, "status": "resuming"}


@router.post("/{graph_run_id}/retry")
async def retry_auto_run(graph_run_id: str) -> dict[str, Any]:
    """Retry a hard-failed batch step from exactly the batch it stopped at
    (see ``retry_auto_pipeline``/``retry_auto_pipeline_from_data``) — never
    restarts the whole run.

    409s when there is nothing resumable: the run isn't currently failed, it
    failed somewhere other than the one step with a batch concept
    (``run_batches`` for a live-connector run, ``pair_values`` for a from-data
    run), or it failed before any batch completed — the same cases the polled
    status's ``resumable`` flag already reflects.
    """
    run = pipeline_run_store.get(graph_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Unknown auto-run '{graph_run_id}'.")
    if run.get("status") != "failed" or not _has_resumable_checkpoint(graph_run_id, run.get("failed_step")):
        raise HTTPException(
            status_code=409,
            detail=f"Auto-run '{graph_run_id}' has no resumable batch failure to retry.",
        )

    trigger_retry(graph_run_id, reason="retry")

    return {"graph_run_id": graph_run_id, "status": "resuming"}
