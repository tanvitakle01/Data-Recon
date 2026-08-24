"""Wires the 8 Auto-mode nodes into a linear LangGraph ``StateGraph`` with a
hard-stop conditional edge after every node: a node that recorded
``status == "failed"`` routes straight to ``END`` instead of continuing, so a
genuine step failure never lets a later step run on incomplete state. A low
match/pairing rate is not a failure signal (see ``nodes.py``), so it never
trips this routing — only an actual raised exception does.

Compiled with a SQLite checkpointer (keyed by ``graph_run_id`` as the
LangGraph ``thread_id``) so a RECOVERABLE node failure — entity/field/join-key
not resolved (see ``interrupts.py``) — can call ``interrupt()`` to pause and
checkpoint instead of hard-stopping, and later resume from exactly that node
via :func:`resume_auto_pipeline`. Persisted to disk (not ``MemorySaver``) so a
paused run survives a process restart, matching the durability
``pipeline_run_store`` already gives the rest of a run's state.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Callable

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from backend.recon_engine.auto_pipeline import nodes
from backend.recon_engine.auto_pipeline.state import AutoRunState
from backend.recon_engine.config import get_settings

_NODE_ORDER = [
    ("select_source", nodes.select_source),
    ("select_target", nodes.select_target),
    ("resolve_schema", nodes.resolve_schema),
    ("compile_contract", nodes.compile_contract),
    ("plan_date_batches", nodes.plan_date_batches),
    ("run_batches", nodes.run_batches),
    ("finalize", nodes.finalize),
]

# The node immediately before "run_batches" — retry_auto_pipeline() rewrites
# graph state as if THIS node just completed, so LangGraph schedules
# run_batches next (see that function's docstring).
_NODE_BEFORE_RUN_BATCHES = "plan_date_batches"


def _open_checkpointer() -> SqliteSaver:
    settings = get_settings()
    settings.ensure_dirs()
    # check_same_thread=False: each Auto-run request executes on its own
    # worker thread (asyncio.to_thread) — SqliteSaver serializes access to
    # this connection internally via its own lock, so this is the documented,
    # safe way to share one connection across those threads.
    conn = sqlite3.connect(
        str(settings.store_dir / "auto_pipeline_checkpoints.db"),
        check_same_thread=False,
    )
    return SqliteSaver(conn)


def _build_graph():
    graph = StateGraph(AutoRunState)
    for name, fn in _NODE_ORDER:
        graph.add_node(name, fn)

    graph.add_edge(START, _NODE_ORDER[0][0])
    for i, (name, _fn) in enumerate(_NODE_ORDER[:-1]):
        next_name = _NODE_ORDER[i + 1][0]

        def _router(state, _next=next_name):
            return END if state.get("status") in ("failed", "cancelled", "suspended") else _next

        graph.add_conditional_edges(name, _router, [next_name, END])
    graph.add_edge(_NODE_ORDER[-1][0], END)

    return graph.compile(checkpointer=_open_checkpointer())


_COMPILED = _build_graph()


def _thread_config(graph_run_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": graph_run_id}}


def _stream_and_merge(
    input_: Any,
    config: dict[str, Any],
    seed: AutoRunState,
    on_step: Callable[[str, AutoRunState], None] | None,
    compiled: Any = None,
) -> AutoRunState:
    """``compiled`` defaults to this module's full 8-node graph; passed
    explicitly by ``graph_from_data.py`` to reuse this exact merge/streaming
    logic over its own 4-node graph instead of duplicating it."""
    graph_obj = compiled if compiled is not None else _COMPILED
    merged: AutoRunState = dict(seed)
    for chunk in graph_obj.stream(input_, config=config, stream_mode="updates"):
        for step_name, update in chunk.items():
            if step_name == "__interrupt__":
                # Handled by get_pending_interrupt() after streaming ends —
                # not a node update, nothing to merge into state here.
                continue
            merged.update(update)
            if on_step is not None:
                on_step(step_name, dict(merged))
    return merged


def run_auto_pipeline(initial_state: AutoRunState) -> AutoRunState:
    """Run the Auto-mode pipeline synchronously to completion, hard-stop, or a
    RECOVERABLE pause.

    Meant to be invoked from a worker thread (``asyncio.to_thread``) — every
    node underneath is a plain blocking call over existing synchronous
    business logic, matching the rest of this codebase.
    """
    state: AutoRunState = dict(initial_state)
    state.setdefault("status", "running")
    state.setdefault("step_timestamps", {})
    return _COMPILED.invoke(state, config=_thread_config(state["graph_run_id"]))


def stream_auto_pipeline(
    initial_state: AutoRunState,
    on_step: Callable[[str, AutoRunState], None] | None = None,
) -> AutoRunState:
    """Like :func:`run_auto_pipeline`, but invokes ``on_step(step_name, state)``
    after every node completes — the hook the polling status endpoint uses to
    record live progress (current step, per-step timestamps) as the pipeline
    runs, rather than only once at the very end.
    """
    state: AutoRunState = dict(initial_state)
    state.setdefault("status", "running")
    state.setdefault("step_timestamps", {})
    config = _thread_config(state["graph_run_id"])
    return _stream_and_merge(state, config, seed=state, on_step=on_step)


def resume_auto_pipeline(
    graph_run_id: str,
    resume_value: Any,
    on_step: Callable[[str, AutoRunState], None] | None = None,
) -> AutoRunState:
    """Resume a paused run with a validated answer — from EXACTLY the node
    that called ``interrupt()``, never from ``START``.

    ``resume_value`` is injected via LangGraph's ``Command(resume=...)``
    primitive and matched to the pending interrupt on this thread
    (``graph_run_id``). Every node that already completed before the pause is
    restored from its checkpoint, not re-executed — only the interrupted
    node's function body re-runs (LangGraph's documented resume semantics),
    and it re-validates the (possibly still-wrong) answer against the same
    live options before accepting it (see ``interrupts.py``).
    """
    config = _thread_config(graph_run_id)
    seed = _COMPILED.get_state(config).values or {}
    return _stream_and_merge(Command(resume=resume_value), config, seed=seed, on_step=on_step)


def retry_auto_pipeline(
    graph_run_id: str,
    on_step: Callable[[str, AutoRunState], None] | None = None,
) -> AutoRunState:
    """Retry a HARD-FAILED ``run_batches`` node from exactly the date batch it
    stopped at, using whatever ``run_batch_checkpoint`` row
    ``nodes._do_run_batches`` already persisted for the batches that resolved
    before the failure (see ``storage.pipeline_run_store.
    save_run_batch_checkpoint``).

    Unlike :func:`resume_auto_pipeline` (which resumes a live ``interrupt()``
    pause via ``Command(resume=...)``), a hard failure (``status: "failed"``,
    routed straight to ``END`` by ``_router``) leaves no pending interrupt to
    resume — ``get_pending_interrupt`` returns ``None`` for this thread. So
    instead this rewrites the checkpoint via ``update_state(...,
    as_node=_NODE_BEFORE_RUN_BATCHES)`` — the node immediately before
    ``run_batches`` — clearing ``status``/``failed_step``/``error`` as part of
    the same write. LangGraph then schedules whatever node that node's own
    edge points at (``run_batches``) as the next step, so invoking with no new
    input re-executes ONLY ``run_batches``, not the whole graph from
    ``START``. ``run_batches`` itself reads ``pipeline_run_store.
    get_run_batch_checkpoint`` and skips every batch already resolved.
    """
    config = _thread_config(graph_run_id)
    seed = _COMPILED.get_state(config).values or {}
    values = {**seed, "status": "running", "failed_step": None, "error": None}
    _COMPILED.update_state(config, values, as_node=_NODE_BEFORE_RUN_BATCHES)
    return _stream_and_merge(None, config, seed=values, on_step=on_step)


def resume_suspended_pipeline(
    graph_run_id: str,
    on_step: Callable[[str, AutoRunState], None] | None = None,
) -> AutoRunState:
    """Resume a SUSPENDED run from exactly the batch it was parked at, using
    whatever ``run_batch_checkpoint`` row ``nodes._do_run_batches`` already
    persisted for the batches that completed before the suspend took effect
    (see ``storage.pipeline_run_store.save_run_batch_checkpoint``).

    Copy-modeled on :func:`retry_auto_pipeline`, not :func:`resume_auto_pipeline`:
    a suspend (like a hard failure) leaves no pending ``interrupt()`` to answer
    via ``Command(resume=...)`` — it cooperatively returned ``status:
    "suspended"`` from between two date-batches, routed straight to ``END`` by
    ``_router``. So this rewrites the checkpoint via ``update_state(...,
    as_node=_NODE_BEFORE_RUN_BATCHES)`` exactly like a retry, which is safe
    here specifically because a suspend can only ever take effect once
    ``plan_date_batches`` has already completed (see ``nodes.py``'s
    ``_do_run_batches`` loop, the only place the suspend signal is checked) —
    every field this rewrite implicitly relies on (contract_id, source_spec,
    the batch plan) is therefore already present in the checkpointed state.
    """
    config = _thread_config(graph_run_id)
    seed = _COMPILED.get_state(config).values or {}
    values = {**seed, "status": "running", "failed_step": None, "error": None}
    _COMPILED.update_state(config, values, as_node=_NODE_BEFORE_RUN_BATCHES)
    return _stream_and_merge(None, config, seed=values, on_step=on_step)


def get_run_state_values(graph_run_id: str) -> AutoRunState:
    """The run's current checkpointed state — used by the suspend/resume
    routes to read ``source_spec``/``target_spec``/``*_field_roles`` for the
    staleness fingerprint (see ``data_fingerprint.py``) without duplicating
    LangGraph's own checkpoint access. Empty dict if the thread has no
    checkpoint yet (shouldn't happen for any run past ``CREATED``)."""
    return _COMPILED.get_state(_thread_config(graph_run_id)).values or {}


def get_pending_interrupt(graph_run_id: str) -> Any | None:
    """The live interrupt payload for a paused thread, or ``None`` if the run
    isn't currently paused waiting on a resolver answer."""
    snapshot = _COMPILED.get_state(_thread_config(graph_run_id))
    if not snapshot.interrupts:
        return None
    return snapshot.interrupts[0].value
