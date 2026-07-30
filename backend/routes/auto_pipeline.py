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

from backend.recon_engine.auto_pipeline.graph import stream_auto_pipeline
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
    )


def _execute(graph_run_id: str, initial_state: AutoRunState) -> None:
    try:
        final_state = stream_auto_pipeline(
            initial_state, on_step=lambda step, s: _on_step(graph_run_id, step, s)
        )
    except Exception as exc:  # noqa: BLE001 - a bug in the graph itself, not a modeled step failure
        pipeline_run_store.update(graph_run_id, status="failed", error=str(exc))
        return

    pipeline_run_store.update(
        graph_run_id,
        status=final_state.get("status", "failed"),
        step_timestamps=final_state.get("step_timestamps") or {},
        failed_step=final_state.get("failed_step"),
        error=final_state.get("error"),
        result=_partial_result(final_state),
    )


async def _run_in_background(graph_run_id: str, initial_state: AutoRunState) -> None:
    await asyncio.to_thread(_execute, graph_run_id, initial_state)


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
