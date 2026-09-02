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

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from pydantic import BaseModel, Field

from backend.excel_comparator.core.loader import load_tabular
from backend.recon_engine import run_registry, service
from backend.recon_engine.auto_pipeline import data_fingerprint
from backend.recon_engine.auto_pipeline.date_batching import DateBatch
from backend.recon_engine.auto_pipeline.graph import (
    get_pending_interrupt,
    get_run_state_values,
    resume_auto_pipeline,
    resume_suspended_pipeline,
    retry_auto_pipeline,
    stream_auto_pipeline,
)
from backend.recon_engine.auto_pipeline.state import AutoRunState
from backend.recon_engine.models.snapshot import RawLayer
from backend.recon_engine.run_registry import RunState
from backend.recon_engine.storage import (
    pipeline_run_store,
    result_store,
    run_value_mapping_store,
    value_pair_store,
)

logger = logging.getLogger("recon.routes.auto_pipeline")

router = APIRouter(prefix="/api/recon/auto-run", tags=["recon-auto-pipeline"])

# Default parking window for a suspended run before the expiry watchdog
# discards it (see main.py's watchdog tick) — confirmed with the user.
SUSPENSION_EXPIRY_DAYS = 30

# Keeps a strong reference to in-flight background tasks — asyncio does not
# guarantee a task survives if nothing else holds it, and the request that
# created it returns immediately.
_background_tasks: set[asyncio.Task] = set()

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
    the graph's own checkpoint, the single source of truth for whether a
    thread is actually waiting.
    """
    pending = get_pending_interrupt(graph_run_id)
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
    elif to_state == RunState.COMPLETED:
        # Promotes every value pairing THIS run discovered mid-batch and
        # tagged 'provisional' (see value_pair_store.propose) to 'promoted' —
        # the one place a run's provisional pairings graduate to the global
        # library, since a run reaching here has gone all the way through.
        value_pair_store.promote_run(graph_run_id)
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
    try:
        final_state = stream_auto_pipeline(initial_state, on_step=lambda step, s: _on_step(graph_run_id, step, s))
    except Exception as exc:  # noqa: BLE001 - a bug in the graph itself, not a modeled step failure
        _fail_hard(graph_run_id, exc)
        return
    _finish(graph_run_id, final_state)


def _execute_resume(graph_run_id: str, resume_value: str) -> None:
    try:
        final_state = resume_auto_pipeline(
            graph_run_id, resume_value, on_step=lambda step, s: _on_step(graph_run_id, step, s)
        )
    except Exception as exc:  # noqa: BLE001 - a bug in the graph itself, not a modeled step failure
        _fail_hard(graph_run_id, exc)
        return
    _finish(graph_run_id, final_state)


def _execute_retry(graph_run_id: str) -> None:
    try:
        final_state = retry_auto_pipeline(graph_run_id, on_step=lambda step, s: _on_step(graph_run_id, step, s))
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
    """Ingests two already-loaded DataFrames as snapshots and starts the SAME
    7-node Auto-mode graph a mapping-sheet/live-connector run uses — with
    ``kind="upload"`` on both sides, select_source/select_target/
    resolve_schema simply skip live entity/schema resolution (see
    ``auto_pipeline/nodes.py``) since everything needed is already known from
    the ingested snapshot. Shared by the ``/start-from-data`` route and the
    chat orchestrator."""
    graph_run_id = pipeline_run_store.new_graph_run_id()

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
    no live connector — runs the same Auto-mode graph as any other run (see
    ``start_auto_run_from_data_state``)."""
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
    """Every run — regardless of source kind — batches the WHOLE
    extract+pair+reconcile sequence inside ``run_batches`` (one checkpoint per
    run — see ``pipeline_run_store.has_run_batch_checkpoint``).

    ``finalize`` is resumable too, alongside ``run_batches`` itself: a retry
    re-enters the graph one node before ``run_batches`` regardless of which of
    the two actually failed (see ``auto_pipeline.graph.retry_auto_pipeline``),
    and the checkpoint's ``next_batch_index`` already equals ``batch_count``
    for a run that made it all the way to (and failed at) ``finalize`` — so
    ``_do_run_batches``' loop is a no-op and it falls straight through to a
    fresh ``finalize`` attempt, never redoing a batch. Requires the checkpoint
    to still exist — see ``auto_pipeline.nodes._do_finalize``, which only
    clears it AFTER a successful finalize, precisely so this stays true for a
    finalize failure."""
    return (
        failed_step in ("run_batches", "finalize")
        and pipeline_run_store.has_run_batch_checkpoint(graph_run_id)
    )


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

    - RUNNING: flips to SUSPENDING (the cooperative signal
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


def trigger_resume(graph_run_id: str, *, force: bool = False, source: str = "chat") -> dict[str, Any]:
    """Flips a SUSPENDED run back to RUNNING and kicks off
    :func:`resume_suspended_pipeline` in the background — the exact side
    effect ``POST /{id}/resume`` performs, factored out so the chat
    orchestrator's resume path can trigger the same thing without going
    through HTTP (mirrors :func:`trigger_retry`'s existing shape).

    Raises ``ValueError("stale")`` if the connector-side data has moved since
    suspend and ``force`` wasn't set — it's the caller's responsibility to
    surface the staleness question and retry with ``force=True`` once the
    user decides.

    Deliberately does NOT delete the suspension row: the Stored Runs tab
    tracks "runs touched from here" regardless of current status, staying
    visible through RUNNING and into COMPLETED/FAILED until the user
    explicitly deletes it (see ``list_stored_runs``/``delete_stored_run``).

    ``source`` is stamped onto the transition's ``reason`` as ``"resume:
    <source>"`` — the ONLY record of where a resume came from (Stored Runs
    tab vs. chat's own "resume <name>"), since chat needs to tell a user
    "this run was resumed from the Stored Runs tab at <time>" even when that
    resume didn't happen through chat at all (see ``run_registry.
    last_resume_transition`` / ``chat_assistant.orchestrator._status_reply``).
    """
    suspension = pipeline_run_store.get_suspension(graph_run_id)
    if suspension is not None and not force:
        current = _capture_fingerprint_for(graph_run_id)
        if current is not None and not data_fingerprint.fingerprint_matches(
            suspension["data_fingerprint"], current
        ):
            raise ValueError("stale")

    run = pipeline_run_store.get(graph_run_id)
    run_registry.transition(graph_run_id, RunState.RUNNING, reason=f"resume:{source}")
    pipeline_run_store.update_progress(
        graph_run_id,
        current_step=run.get("current_step") if run else None,
        step_timestamps=(run or {}).get("step_timestamps") or {},
        result=(run or {}).get("result"),
        interrupt=None,
    )
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
    # RUNNING -> SUSPENDING (park takes effect at the next batch boundary);
    # FAILED -> SUSPENDED directly (see trigger_suspend).
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
        return trigger_resume(graph_run_id, force=req.force, source="stored_runs_tab")
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
    """Every run tracked by the Stored Runs tab — every run ever suspended
    from there, REGARDLESS of its current status (suspended/running/completed/
    failed), enriched with progress/expiry. A run stays listed here until the
    user explicitly deletes it (see ``delete_stored_run``) — resuming it does
    NOT remove it (see ``trigger_resume``). A suspension row whose owning
    ``pipeline_runs`` row has vanished entirely (should not normally happen)
    is skipped rather than shown stale."""
    out: list[dict[str, Any]] = []
    for suspension in pipeline_run_store.list_suspensions():
        graph_run_id = suspension["graph_run_id"]
        run = pipeline_run_store.get(graph_run_id)
        if run is None:
            continue
        checkpoint = pipeline_run_store.get_run_batch_checkpoint(graph_run_id)
        plan = pipeline_run_store.get_run_batch_plan(graph_run_id)
        # `batch_progress` (pipeline_runs.batch_progress_json) is a SEPARATE,
        # never-cleared field last written by the batch loop's own progress
        # callback (see auto_pipeline.nodes._report_batch_stage) — the
        # fallback for a run whose checkpoint/plan are already gone (cleared
        # once run_batches finished) but that then hard-failed at `finalize`:
        # without this, such a run misreports "0 batches completed" here even
        # though every batch actually finished (see auto_pipeline.nodes.
        # _do_finalize on why the checkpoint/plan don't survive that case).
        batch_progress = run.get("batch_progress") or {}
        out.append(
            {
                "graph_run_id": graph_run_id,
                "name": suspension["user_name"],
                "status": run.get("status"),
                "suspended_at": suspension["suspended_at"],
                "suspend_reason": suspension["suspend_reason"],
                "expires_at": suspension["expires_at"],
                "batches_completed": (
                    checkpoint["next_batch_index"] if checkpoint else batch_progress.get("batches_completed", 0)
                ),
                "batches_total": (
                    len(plan) if plan
                    else (checkpoint["batch_count"] if checkpoint else batch_progress.get("batch_count"))
                ),
                "result_id": checkpoint["result_id"] if checkpoint else None,
                "batch_progress": run.get("batch_progress"),
            }
        )
    return out


@router.delete("/{graph_run_id}")
def delete_stored_run(graph_run_id: str) -> dict[str, Any]:
    """Removes a run from the Stored Runs tab. A SUSPENDED run is discarded
    outright: transitioned to CANCELLED, its batch plan/checkpoint/
    corroboration/provisional-mappings/suspension rows all dropped (see
    ``pipeline_run_store.cleanup_run_artifacts``). A FAILED/COMPLETED/
    CANCELLED tracked run has nothing left to transition (COMPLETED/CANCELLED
    are terminal; FAILED's only legal edge is back to RUNNING) — deleting it
    is a pure "dismiss from this tab", still routed through the same cleanup
    (a safe no-op for whatever it doesn't apply to; never touches `results`).
    Rejected while the run is actively executing — see ``run_registry.
    ACTIVE_STATES`` — since wiping its checkpoint out from under an in-flight
    batch loop would corrupt it; wait for it to finish first."""
    run = pipeline_run_store.get(graph_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Unknown auto-run '{graph_run_id}'.")
    if pipeline_run_store.get_suspension(graph_run_id) is None:
        raise HTTPException(status_code=404, detail=f"'{graph_run_id}' is not a Stored Runs entry.")
    status = RunState(run.get("status"))
    if status in run_registry.ACTIVE_STATES:
        raise HTTPException(
            status_code=409,
            detail=f"Auto-run '{graph_run_id}' is currently {status.value!r} — wait for it to finish first.",
        )
    if status == RunState.SUSPENDED:
        run_registry.transition(graph_run_id, RunState.CANCELLED, reason="discarded from Stored Runs")
    pipeline_run_store.cleanup_run_artifacts(graph_run_id)
    return {"graph_run_id": graph_run_id, "status": "deleted"}


_BATCH_PREVIEW_ROWS_PER_BATCH = 50


def _batches_total(graph_run_id: str) -> int | None:
    plan = pipeline_run_store.get_run_batch_plan(graph_run_id)
    if plan:
        return len(plan)
    checkpoint = pipeline_run_store.get_run_batch_checkpoint(graph_run_id)
    if checkpoint:
        return checkpoint["batch_count"]
    # Last resort: the never-cleared `batch_progress` field (see
    # list_stored_runs' matching comment) — a run that hard-failed at
    # `finalize` after every batch completed has neither plan nor checkpoint
    # left, but this field still has the real count.
    run = pipeline_run_store.get(graph_run_id)
    return ((run or {}).get("batch_progress") or {}).get("batch_count")


def _load_detail_frame_or_500(result_id: str, graph_run_id: str) -> pd.DataFrame:
    """``result_store.load_result_frame_jsonl`` wrapped with a clear, actionable
    500 instead of a bare pandas ``ValueError`` bubbling up as an opaque
    unhandled-exception 500 — this is the exact spot a corrupted ``.jsonl``
    detail file (a 0-column header written by an old build's empty-batch bug,
    see ``storage.frames.append_frame``'s docstring) used to surface as
    "Couldn't load results for this run" in the Stored Runs UI with no way to
    tell why."""
    try:
        return result_store.load_result_frame_jsonl(result_id)
    except Exception as exc:  # noqa: BLE001 - reporting a corrupt on-disk file, not a coding error
        raise HTTPException(
            status_code=500,
            detail=(
                f"This run's stored detail data ('{result_id}') is corrupted and can't be read "
                f"({exc}). This affects both viewing and exporting its results."
            ),
        ) from exc


@router.get("/{graph_run_id}/partial-results")
def get_partial_results(graph_run_id: str) -> dict[str, Any]:
    """A suspended (or otherwise non-completed) run's completed-batches-so-far
    results, grouped by batch number — read straight from ``result_store``
    (the ``.jsonl`` detail frame), ``run_batch_attempts``, and
    ``run_value_mapping_store`` (that batch's own resolved value-pairing
    decisions), entirely independent of the LangGraph checkpoint, so this
    works without resuming anything. Every completed attempt gets its own
    entry, even one with zero detail rows (the "both sides empty for this
    date window" case — see ``auto_pipeline.nodes._do_run_batches`` — is a
    valid, expected outcome, not an error)."""
    run = pipeline_run_store.get(graph_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Unknown auto-run '{graph_run_id}'.")
    plan = pipeline_run_store.get_run_batch_plan(graph_run_id) or []
    plan_by_index = {entry["batch_index"]: entry for entry in plan}
    # Falls back to the never-cleared `batch_progress` field (see
    # list_stored_runs' matching comment) once the plan itself is gone — a run
    # that hard-failed at `finalize` after every batch completed.
    batches_total = len(plan) or (run.get("batch_progress") or {}).get("batch_count")

    result = result_store.get_result_for_run(graph_run_id)
    if result is None:
        return {
            "result": None,
            "batches": [],
            "batches_completed": 0,
            "batches_total": batches_total,
        }

    detail_df = _load_detail_frame_or_500(result.result_id, graph_run_id)
    attempts = pipeline_run_store.list_batch_attempts(graph_run_id)

    batches: list[dict[str, Any]] = []
    for attempt in attempts:
        plan_entry = plan_by_index.get(attempt["batch_index"])
        label = DateBatch.from_dict(plan_entry).label if plan_entry else f"Batch {attempt['batch_index'] + 1}"
        batch_rows = (
            detail_df[detail_df["batch_id"] == attempt["batch_id"]] if not detail_df.empty else detail_df
        )
        preview_rows = (
            batch_rows.head(_BATCH_PREVIEW_ROWS_PER_BATCH)
            .astype(object)
            .where(batch_rows.notna(), None)
            .to_dict(orient="records")
            if not batch_rows.empty
            else []
        )
        mappings = run_value_mapping_store.get_batch_mappings(graph_run_id, attempt["batch_id"])
        batches.append(
            {
                "batch_index": attempt["batch_index"],
                "batch_label": label,
                "row_count": len(batch_rows),
                "preview_rows": preview_rows,
                "mappings": [m.model_dump(mode="json") for m in mappings],
            }
        )

    return {
        "result": result.model_dump(mode="json"),
        "batches": batches,
        "batches_completed": len(batches),
        "batches_total": batches_total,
    }


@router.get("/{graph_run_id}/partial-results/export")
def export_partial_results(graph_run_id: str) -> StreamingResponse:
    """Raw CSV of every completed batch's detail rows so far — the completed-
    batches-only data, same scope as ``get_partial_results``' View panel.
    Filename is labeled with the batches-completed/-total count so a partial
    export is never mistaken for a complete one. For a COMPLETED run, use the
    normal ``/comparison.xlsx`` artifact instead (same one a normally-
    completed run gets) — this route stays raw/unenriched because a
    non-completed run has no ``run_store`` row for that route to key off."""
    run = pipeline_run_store.get(graph_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Unknown auto-run '{graph_run_id}'.")
    result = result_store.get_result_for_run(graph_run_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No results recorded yet for '{graph_run_id}'.")
    detail_df = _load_detail_frame_or_500(result.result_id, graph_run_id)
    buffer = io.StringIO()
    detail_df.to_csv(buffer, index=False)
    buffer.seek(0)

    batches_completed = len(pipeline_run_store.list_batch_attempts(graph_run_id))
    batches_total = _batches_total(graph_run_id)
    label = f"{batches_completed}of{batches_total if batches_total is not None else '?'}batches"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{graph_run_id}_partial_{label}.csv"'},
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
    if run.get("status") == RunState.RUNNING.value:
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
    (see ``retry_auto_pipeline``) — never restarts the whole run.

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
