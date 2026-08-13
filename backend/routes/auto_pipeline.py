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

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.recon_engine.auto_pipeline.graph import (
    get_pending_interrupt,
    resume_auto_pipeline,
    stream_auto_pipeline,
)
from backend.recon_engine.auto_pipeline.state import AutoRunState
from backend.recon_engine.storage import pipeline_run_store

router = APIRouter(prefix="/api/recon/auto-run", tags=["recon-auto-pipeline"])

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
    pipeline_run_store.update(
        graph_run_id,
        status=state.get("status", "running"),
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
    """Record a stream's outcome: completed, hard-failed, or RECOVERABLY
    paused waiting on the resolver bot's next answer.

    A pause never returns a "completed"/"failed" status from the stream
    itself (the interrupting node raised instead of returning) — checked via
    :func:`get_pending_interrupt` against the graph's own checkpoint, the
    single source of truth for whether a thread is actually waiting.
    """
    pending = get_pending_interrupt(graph_run_id)
    if pending is not None:
        pipeline_run_store.update(
            graph_run_id,
            status="waiting_for_input",
            step_timestamps=final_state.get("step_timestamps") or {},
            failed_step=None,
            error=None,
            result=_partial_result(final_state),
            interrupt=pending,
        )
        return

    pipeline_run_store.update(
        graph_run_id,
        status=final_state.get("status", "failed"),
        step_timestamps=final_state.get("step_timestamps") or {},
        failed_step=final_state.get("failed_step"),
        error=final_state.get("error"),
        result=_partial_result(final_state),
        interrupt=None,
    )


def _execute(graph_run_id: str, initial_state: AutoRunState) -> None:
    try:
        final_state = stream_auto_pipeline(
            initial_state, on_step=lambda step, s: _on_step(graph_run_id, step, s)
        )
    except Exception as exc:  # noqa: BLE001 - a bug in the graph itself, not a modeled step failure
        pipeline_run_store.update(graph_run_id, status="failed", error=str(exc), interrupt=None)
        return
    _finish(graph_run_id, final_state)


def _execute_resume(graph_run_id: str, resume_value: str) -> None:
    try:
        final_state = resume_auto_pipeline(
            graph_run_id, resume_value, on_step=lambda step, s: _on_step(graph_run_id, step, s)
        )
    except Exception as exc:  # noqa: BLE001 - a bug in the graph itself, not a modeled step failure
        pipeline_run_store.update(graph_run_id, status="failed", error=str(exc), interrupt=None)
        return
    _finish(graph_run_id, final_state)


async def _run_in_background(graph_run_id: str, initial_state: AutoRunState) -> None:
    await asyncio.to_thread(_execute, graph_run_id, initial_state)


async def _resume_in_background(graph_run_id: str, resume_value: str) -> None:
    await asyncio.to_thread(_execute_resume, graph_run_id, resume_value)


@router.post("/start")
async def start_auto_run(req: AutoRunStartRequest) -> dict[str, Any]:
    graph_run_id = pipeline_run_store.new_graph_run_id()
    pipeline_run_store.create(graph_run_id)

    initial_state: AutoRunState = {
        "graph_run_id": graph_run_id,
        "actor": req.actor,
        "comparison_type": req.comparison_type,
        "mapping_sheet": req.mapping_sheet,
        "identification": req.identification,
    }
    task = asyncio.create_task(_run_in_background(graph_run_id, initial_state))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return {"graph_run_id": graph_run_id}


@router.get("/{graph_run_id}/status")
def get_auto_run_status(graph_run_id: str) -> dict[str, Any]:
    run = pipeline_run_store.get(graph_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Unknown auto-run '{graph_run_id}'.")
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

    pipeline_run_store.update(
        graph_run_id,
        status="running",
        current_step=run.get("current_step"),
        step_timestamps=run.get("step_timestamps") or {},
        result=run.get("result"),
        interrupt=None,
    )
    task = asyncio.create_task(_resume_in_background(graph_run_id, req.value))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return {"graph_run_id": graph_run_id, "status": "resuming"}
