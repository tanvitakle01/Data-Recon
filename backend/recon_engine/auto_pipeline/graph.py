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
    ("import_source", nodes.import_source),
    ("select_target", nodes.select_target),
    ("import_target", nodes.import_target),
    ("identify_candidate_keys", nodes.identify_candidate_keys_step),
    ("extract_unique_keys", nodes.extract_unique_keys),
    ("pair_values", nodes.pair_values_step),
    ("compile_and_run", nodes.compile_and_run),
]


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
            return END if state.get("status") == "failed" else _next

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
) -> AutoRunState:
    merged: AutoRunState = dict(seed)
    for chunk in _COMPILED.stream(input_, config=config, stream_mode="updates"):
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


def get_pending_interrupt(graph_run_id: str) -> Any | None:
    """The live interrupt payload for a paused thread, or ``None`` if the run
    isn't currently paused waiting on a resolver answer."""
    snapshot = _COMPILED.get_state(_thread_config(graph_run_id))
    if not snapshot.interrupts:
        return None
    return snapshot.interrupts[0].value
