"""A second, shorter Auto-mode graph for chat-uploaded source/target files.

``graph.py``'s compiled graph always starts at ``select_source`` (a live
SAP/IBP connector fetch — see ``registry.py``, which has no "uploaded file"
connector kind). When the chatbot already has two uploaded CSV/Excel files
instead of a live connector, there is nothing for steps 1-4 to do: the caller
ingests each file as a snapshot itself (``service.ingest_snapshot``) and seeds
``AutoRunState["source"]``/``["target"]`` directly.

This module compiles the last 4 steps of ``graph.py``'s Auto-mode sequence
into their own linear graph — ``identify_candidate_keys`` and
``extract_unique_keys`` reused unchanged, ``compile_and_run`` reused unchanged
(it never detects roles itself), but ``pair_values`` swapped for
``nodes_from_data.pair_values_step_from_data``: chat-uploaded files use
LLM-based date/quantity role detection instead of the live-connector path's
fixed alias list, which real-world exports (``Req.Dlv.Dt``, ``KEYFIGUREDATE``,
etc.) routinely miss — see ``nodes_from_data.py`` and ``business_key_roles.py``.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Callable

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from backend.recon_engine.auto_pipeline import nodes, nodes_from_data
from backend.recon_engine.auto_pipeline.graph import _stream_and_merge
from backend.recon_engine.auto_pipeline.state import AutoRunState
from backend.recon_engine.config import get_settings

_NODE_ORDER_FROM_DATA = [
    ("identify_candidate_keys", nodes.identify_candidate_keys_step),
    ("extract_unique_keys", nodes.extract_unique_keys),
    ("pair_values", nodes_from_data.pair_values_step_from_data),
    ("compile_and_run", nodes.compile_and_run),
]


def _open_checkpointer() -> SqliteSaver:
    settings = get_settings()
    settings.ensure_dirs()
    # A separate checkpoint file from the full graph's — different node set
    # compiled into the graph object means a different (incompatible) set of
    # checkpoint channels, even though graph_run_ids never collide between
    # the two (see the "autorun_fd_" prefix in routes/auto_pipeline.py).
    conn = sqlite3.connect(
        str(settings.store_dir / "auto_pipeline_from_data_checkpoints.db"),
        check_same_thread=False,
    )
    return SqliteSaver(conn)


def _build_graph():
    graph = StateGraph(AutoRunState)
    for name, fn in _NODE_ORDER_FROM_DATA:
        graph.add_node(name, fn)

    graph.add_edge(START, _NODE_ORDER_FROM_DATA[0][0])
    for i, (name, _fn) in enumerate(_NODE_ORDER_FROM_DATA[:-1]):
        next_name = _NODE_ORDER_FROM_DATA[i + 1][0]

        def _router(state, _next=next_name):
            return END if state.get("status") == "failed" else _next

        graph.add_conditional_edges(name, _router, [next_name, END])
    graph.add_edge(_NODE_ORDER_FROM_DATA[-1][0], END)

    return graph.compile(checkpointer=_open_checkpointer())


_COMPILED_FROM_DATA = _build_graph()


def _thread_config(graph_run_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": graph_run_id}}


def stream_auto_pipeline_from_data(
    initial_state: AutoRunState,
    on_step: Callable[[str, AutoRunState], None] | None = None,
) -> AutoRunState:
    """Like ``graph.stream_auto_pipeline``, but over the 4-node graph starting
    from ``identify_candidate_keys`` — ``initial_state["source"]``/``["target"]``
    must already carry a ``snapshot_id`` (the caller ingested the uploaded
    files itself; see ``routes/auto_pipeline.py``'s ``/start-from-data``)."""
    state: AutoRunState = dict(initial_state)
    state.setdefault("status", "running")
    state.setdefault("step_timestamps", {})
    config = _thread_config(state["graph_run_id"])
    return _stream_and_merge(state, config, seed=state, on_step=on_step, compiled=_COMPILED_FROM_DATA)


def resume_auto_pipeline_from_data(
    graph_run_id: str,
    resume_value: Any,
    on_step: Callable[[str, AutoRunState], None] | None = None,
) -> AutoRunState:
    config = _thread_config(graph_run_id)
    seed = _COMPILED_FROM_DATA.get_state(config).values or {}
    return _stream_and_merge(
        Command(resume=resume_value), config, seed=seed, on_step=on_step, compiled=_COMPILED_FROM_DATA
    )


def retry_auto_pipeline_from_data(
    graph_run_id: str,
    on_step: Callable[[str, AutoRunState], None] | None = None,
) -> AutoRunState:
    """Like ``graph.retry_auto_pipeline``, but over this module's 4-node
    graph — see that function's docstring for the ``update_state(...,
    as_node=...)`` mechanics this relies on."""
    config = _thread_config(graph_run_id)
    seed = _COMPILED_FROM_DATA.get_state(config).values or {}
    values = {**seed, "status": "running", "failed_step": None, "error": None}
    _COMPILED_FROM_DATA.update_state(config, values, as_node="extract_unique_keys")
    return _stream_and_merge(
        None, config, seed=values, on_step=on_step, compiled=_COMPILED_FROM_DATA
    )


def get_pending_interrupt_from_data(graph_run_id: str) -> Any | None:
    snapshot = _COMPILED_FROM_DATA.get_state(_thread_config(graph_run_id))
    if not snapshot.interrupts:
        return None
    return snapshot.interrupts[0].value
