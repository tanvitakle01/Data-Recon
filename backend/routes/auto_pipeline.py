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
import io
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from pydantic import BaseModel, Field

from backend.excel_comparator.core.loader import load_tabular
from backend.recon_engine import run_registry, service
from backend.recon_engine.auto_pipeline import data_fingerprint
from backend.recon_engine.auto_pipeline.graph import (
    get_pending_interrupt,
    get_run_state_values,
    resume_auto_pipeline,
    resume_suspended_pipeline,
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
from backend.recon_engine.storage import pipeline_run_store, result_store

logger = logging.getLogger("recon.routes.auto_pipeline")

router = APIRouter(prefix="/api/recon/auto-run", tags=["recon-auto-pipeline"])

# Default parking window for a suspended run before the expiry watchdog
# discards it (see main.py's watchdog tick) — confirmed with the user.
SUSPENSION_EXPIRY_DAYS = 30

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


class AutoRunSuspendRequest(BaseModel):
    name: str | None = None
    reason: str = "user requested suspend"


class AutoRunResumeRequest(BaseModel):
    # True only after the caller has already been shown a staleness mismatch
    # (see /resume's 409 response) and explicitly chose to proceed anyway,
    # accepting a run that mixes two data vintages.
    force: bool = False


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
        "suspended": RunState.SUSPENDED,
    }.get(node_status, RunState.FAILED)
    reason = final_state.get("error") or f"node status={node_status!r}"
    run_registry.transition(graph_run_id, to_state, reason=reason)
    if to_state == RunState.CANCELLED:
        # Nothing about a cancelled run is ever resumable (retry/resume both
        # gate on other statuses) — safe to drop its batch plan/checkpoint/
        # corroboration state now rather than leak it until an unrelated
        # cleanup happens to run. See pipeline_run_store.cleanup_run_artifacts.
        pipeline_run_store.cleanup_run_artifacts(graph_run_id)
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


def _capture_fingerprint_for(graph_run_id: str) -> dict[str, Any] | None:
    """Best-effort staleness fingerprint from the run's current checkpointed
    state — ``None`` if the run hasn't reached ``resolve_schema`` yet (no
    ``*_spec``/``*_field_roles`` to resolve an entity/date-field from), which
    only matters if someone suspends within the first couple of steps; nothing
    meaningful has been extracted yet in that case anyway."""
    state = get_run_state_values(graph_run_id)
    required = ("source_spec", "target_spec", "source_field_roles", "target_field_roles")
    if any(state.get(k) is None for k in required):
        return None
    try:
        return data_fingerprint.capture_fingerprint(
            source_kind=state["source"]["kind"],
            source_spec=state["source_spec"],
            source_date_field=state["source_field_roles"]["date"],
            target_kind=state["target"]["kind"],
            target_spec=state["target_spec"],
            target_date_field=state["target_field_roles"]["date"],
        )
    except Exception:
        # A live connector call (count_entity) backs this fingerprint — a
        # transient connector failure (e.g. a TLS trust issue or a 403 from
        # SAP) must never block the suspend itself. ``fingerprint_matches``
        # already treats a missing fingerprint as "does not match" (fail-safe
        # degrade to asking the user at resume time), so losing it here is
        # safe; crashing the whole chat turn over it is not.
        logger.warning(
            "Could not capture suspend fingerprint for run %s; proceeding without one.",
            graph_run_id, exc_info=True,
        )
        return None


def trigger_suspend(graph_run_id: str, *, name: str | None = None, reason: str = "user requested suspend") -> None:
    """Requests a suspend and records the ``pipeline_run_suspensions`` row,
    capturing the staleness fingerprint against the state at REQUEST time
    (not whatever batch happens to be mid-flight once a cooperative signal is
    actually observed). Two paths, depending on the run's current status:

    - RUNNING/STALLED: flips to SUSPENDING (the cooperative signal
      ``nodes._do_run_batches``' between-batch loop checks) — actually
      parking the run (SUSPENDING -> SUSPENDED) happens asynchronously, the
      same way CANCELLING -> CANCELLED already does. This is the "user
      explicitly pauses" trigger.
    - FAILED (with a resumable ``run_batch_checkpoint`` — same gate
      ``/retry`` uses): a DIRECT FAILED -> SUSPENDED conversion, since the run
      has already stopped (e.g. a network error mid ``run_batches``) — there
      is no cooperative checkpoint left to wait for. This is the "network
      error / interruption" trigger, offered alongside the existing retry
      path rather than only failing outright.

    Raises ``run_registry.IllegalTransition`` for any other current status
    (e.g. WAITING_FOR_INPUT — resolve that first, or cancel instead; or a
    FAILED run with nothing resumable to park)."""
    run = pipeline_run_store.get(graph_run_id)
    current_status = (run or {}).get("status")
    default_name = name or f"{graph_run_id}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    fingerprint = _capture_fingerprint_for(graph_run_id)
    expires_at = (datetime.now(timezone.utc) + timedelta(days=SUSPENSION_EXPIRY_DAYS)).isoformat()

    if current_status == RunState.FAILED.value:
        if not _has_resumable_checkpoint(graph_run_id, (run or {}).get("failed_step")):
            raise run_registry.IllegalTransition(
                f"Run {graph_run_id!r} failed with nothing resumable to park — nothing to suspend."
            )
        run_registry.transition(graph_run_id, RunState.SUSPENDED, reason=reason)
    else:
        run_registry.transition(graph_run_id, RunState.SUSPENDING, reason=reason)

    pipeline_run_store.save_suspension(
        graph_run_id,
        user_name=default_name,
        suspend_reason=reason,
        data_fingerprint=fingerprint or {},
        expires_at=expires_at,
    )


def trigger_resume(graph_run_id: str, *, force: bool = False) -> dict[str, Any]:
    """Flips a SUSPENDED run back to RUNNING and kicks off
    :func:`resume_suspended_pipeline` in the background — the exact side
    effect ``POST /{id}/resume`` performs, factored out so the chat
    orchestrator's resume path can trigger the same thing without going
    through HTTP (mirrors :func:`trigger_retry`'s existing shape).

    Raises ``ValueError("stale")`` if the connector-side data has moved since
    suspend and ``force`` wasn't set — it's the caller's responsibility to
    surface the staleness question and retry with ``force=True`` once the
    user decides.
    """
    suspension = pipeline_run_store.get_suspension(graph_run_id)
    if suspension is not None and not force:
        current = _capture_fingerprint_for(graph_run_id)
        if current is not None and not data_fingerprint.fingerprint_matches(
            suspension["data_fingerprint"], current
        ):
            raise ValueError("stale")

    run = pipeline_run_store.get(graph_run_id)
    run_registry.transition(graph_run_id, RunState.RUNNING, reason="resume")
    pipeline_run_store.update_progress(
        graph_run_id,
        current_step=run.get("current_step") if run else None,
        step_timestamps=(run or {}).get("step_timestamps") or {},
        result=(run or {}).get("result"),
        interrupt=None,
    )
    pipeline_run_store.delete_suspension(graph_run_id)
    task = asyncio.create_task(_resume_suspended_in_background(graph_run_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return {"graph_run_id": graph_run_id, "status": "resuming"}


def _execute_resume_suspended(graph_run_id: str) -> None:
    try:
        final_state = resume_suspended_pipeline(
            graph_run_id, on_step=lambda step, s: _on_step(graph_run_id, step, s)
        )
    except Exception as exc:  # noqa: BLE001 - a bug in the graph itself, not a modeled step failure
        _fail_hard(graph_run_id, exc)
        return
    _finish(graph_run_id, final_state)


async def _resume_suspended_in_background(graph_run_id: str) -> None:
    await asyncio.to_thread(_execute_resume_suspended, graph_run_id)


@router.post("/{graph_run_id}/suspend")
async def suspend_auto_run(graph_run_id: str, req: AutoRunSuspendRequest) -> dict[str, Any]:
    """Offer-and-accept suspend (Section 3 of the build) — never automatic.
    A decline is the caller's responsibility to turn into a CANCEL instead
    (this route only ever parks a run, never discards one)."""
    run = pipeline_run_store.get(graph_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Unknown auto-run '{graph_run_id}'.")
    try:
        trigger_suspend(graph_run_id, name=req.name, reason=req.reason)
    except run_registry.IllegalTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    # RUNNING/STALLED -> SUSPENDING (park takes effect at the next batch
    # boundary); FAILED -> SUSPENDED directly (see trigger_suspend).
    return {"graph_run_id": graph_run_id, "status": run_registry.current_state(graph_run_id).value}


@router.post("/{graph_run_id}/resume")
async def resume_auto_run(graph_run_id: str, req: AutoRunResumeRequest) -> dict[str, Any]:
    run = pipeline_run_store.get(graph_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Unknown auto-run '{graph_run_id}'.")
    if run.get("status") != RunState.SUSPENDED.value:
        raise HTTPException(
            status_code=409, detail=f"Auto-run '{graph_run_id}' is not suspended (status={run.get('status')!r})."
        )
    try:
        return trigger_resume(graph_run_id, force=req.force)
    except ValueError:
        raise HTTPException(
            status_code=409,
            detail=(
                "Source/target data has changed since this run was suspended. "
                "Resume anyway (mixing two data vintages) with force=true, or discard "
                "this run and start fresh."
            ),
        )


@router.get("/stored")
def list_stored_runs() -> list[dict[str, Any]]:
    """Every currently-SUSPENDED run, enriched with progress/expiry for the
    Stored Runs tab. A suspension row whose owning ``pipeline_runs`` status has
    since drifted away from SUSPENDED (resumed/deleted by a racing request) is
    skipped rather than shown stale."""
    out: list[dict[str, Any]] = []
    for suspension in pipeline_run_store.list_suspensions():
        graph_run_id = suspension["graph_run_id"]
        run = pipeline_run_store.get(graph_run_id)
        if run is None or run.get("status") != RunState.SUSPENDED.value:
            continue
        checkpoint = pipeline_run_store.get_run_batch_checkpoint(graph_run_id)
        plan = pipeline_run_store.get_run_batch_plan(graph_run_id)
        out.append(
            {
                "graph_run_id": graph_run_id,
                "name": suspension["user_name"],
                "suspended_at": suspension["suspended_at"],
                "suspend_reason": suspension["suspend_reason"],
                "expires_at": suspension["expires_at"],
                "batches_completed": checkpoint["next_batch_index"] if checkpoint else 0,
                "batches_total": len(plan) if plan else (checkpoint["batch_count"] if checkpoint else None),
                "result_id": checkpoint["result_id"] if checkpoint else None,
            }
        )
    return out


@router.delete("/{graph_run_id}")
def delete_stored_run(graph_run_id: str) -> dict[str, Any]:
    """Discards a SUSPENDED run: transitions it to CANCELLED and drops its
    batch plan/checkpoint/corroboration/suspension rows — never promotes
    anything (there is nothing provisional to promote; every batch's value
    pairings are already in the global library the moment that batch
    completed, see value_pairing/pipeline.py's module docstring)."""
    run = pipeline_run_store.get(graph_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Unknown auto-run '{graph_run_id}'.")
    if run.get("status") != RunState.SUSPENDED.value:
        raise HTTPException(
            status_code=409, detail=f"Auto-run '{graph_run_id}' is not suspended (status={run.get('status')!r})."
        )
    run_registry.transition(graph_run_id, RunState.CANCELLED, reason="discarded from Stored Runs")
    pipeline_run_store.cleanup_run_artifacts(graph_run_id)
    return {"graph_run_id": graph_run_id, "status": "cancelled"}


@router.get("/{graph_run_id}/partial-results")
def get_partial_results(graph_run_id: str) -> dict[str, Any]:
    """A suspended (or otherwise non-completed) run's completed-batches-so-far
    results — read straight from ``result_store``, entirely independent of the
    LangGraph checkpoint, so this works without resuming anything."""
    run = pipeline_run_store.get(graph_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Unknown auto-run '{graph_run_id}'.")
    result = result_store.get_result_for_run(graph_run_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No results recorded yet for '{graph_run_id}'.")
    detail_df = result_store.load_result_frame_jsonl(result.result_id).head(200)
    preview_rows = (
        detail_df.astype(object).where(detail_df.notna(), None).to_dict(orient="records")
        if not detail_df.empty else []
    )
    return {"result": result.model_dump(mode="json"), "preview_rows": preview_rows}


@router.get("/{graph_run_id}/partial-results/export")
def export_partial_results(graph_run_id: str) -> StreamingResponse:
    run = pipeline_run_store.get(graph_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Unknown auto-run '{graph_run_id}'.")
    result = result_store.get_result_for_run(graph_run_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No results recorded yet for '{graph_run_id}'.")
    detail_df = result_store.load_result_frame_jsonl(result.result_id)
    buffer = io.StringIO()
    detail_df.to_csv(buffer, index=False)
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{graph_run_id}_partial_results.csv"'},
    )


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
    # Suspend only makes sense once the run has reached the batching stage
    # (see trigger_suspend/_capture_fingerprint_for) — offering it any
    # earlier would let a user "suspend" a run that has nothing checkpointed
    # yet to resume from. A FAILED run is also suspendable (alongside the
    # existing retry option) exactly when it's resumable at all — the
    # "network error / interruption" trigger point.
    if run.get("status") in (RunState.RUNNING.value, RunState.STALLED.value):
        run["suspendable"] = bool(pipeline_run_store.get_run_batch_plan(graph_run_id))
    elif run.get("status") == RunState.FAILED.value:
        run["suspendable"] = run["resumable"]
    else:
        run["suspendable"] = False
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
