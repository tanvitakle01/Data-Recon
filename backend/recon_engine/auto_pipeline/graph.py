"""Wires the 8 Auto-mode nodes into a linear LangGraph ``StateGraph`` with a
hard-stop conditional edge after every node: a node that recorded
``status == "failed"`` routes straight to ``END`` instead of continuing, so a
genuine step failure never lets a later step run on incomplete state. A low
match/pairing rate is not a failure signal (see ``nodes.py``), so it never
trips this routing — only an actual raised exception does.
"""

from __future__ import annotations

from typing import Callable

from langgraph.graph import END, START, StateGraph

from backend.recon_engine.auto_pipeline import nodes
from backend.recon_engine.auto_pipeline.state import AutoRunState

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

    return graph.compile()


_COMPILED = _build_graph()


def run_auto_pipeline(initial_state: AutoRunState) -> AutoRunState:
    """Run the Auto-mode pipeline synchronously to completion or hard-stop.

    Meant to be invoked from a worker thread (``asyncio.to_thread``) — every
    node underneath is a plain blocking call over existing synchronous
    business logic, matching the rest of this codebase.
    """
    state: AutoRunState = dict(initial_state)
    state.setdefault("status", "running")
    state.setdefault("step_timestamps", {})
    return _COMPILED.invoke(state)


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
    merged: AutoRunState = dict(state)
    for chunk in _COMPILED.stream(state, stream_mode="updates"):
        for step_name, update in chunk.items():
            merged.update(update)
            if on_step is not None:
                on_step(step_name, dict(merged))
    return merged
