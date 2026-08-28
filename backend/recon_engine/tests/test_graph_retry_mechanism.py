"""Standalone proof of the ONE genuinely new LangGraph mechanism this
codebase's retry-from-batch feature relies on: that
``update_state(..., as_node=...)`` followed by ``invoke(None, config)``
re-executes EXACTLY the named node's successor — never the whole graph from
``START`` again, and never a no-op — after a node hard-failed
(``status: "failed"``) and its conditional edge routed the graph to ``END``.

``auto_pipeline.graph.retry_auto_pipeline`` depends on exactly this behavior to
re-run ``run_batches`` after a batch failure without rewinding to
``select_source``/``resolve_schema`` — for every run, regardless of source
kind (live connector or manually-uploaded files both go through this same
graph; see ``auto_pipeline/nodes.py``'s upload branches). This test mirrors this repo's
actual graph shape (``StateGraph`` + ``SqliteSaver`` + a conditional edge that
hard-stops to ``END`` on ``status == "failed"`` — see ``auto_pipeline/graph.py``)
with tiny synthetic nodes instead of real Auto-mode business logic, so it is
fast and has no dependency on snapshot_store/service/connectors. It verifies
the LIBRARY PRIMITIVE the feature is built on, not ``nodes.py`` itself — see
``test_value_pairing.py``'s resume-param test and
``test_auto_pipeline_retry.py``'s route tests for the rest of this feature's
coverage.
"""

from __future__ import annotations

import sqlite3
from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph


class _State(TypedDict, total=False):
    status: str
    failed_step: str | None
    calls: list[str]
    should_fail_b: bool


def _node_a(state: _State) -> dict:
    return {"calls": [*(state.get("calls") or []), "a"]}


def _node_b(state: _State) -> dict:
    calls = [*(state.get("calls") or []), "b"]
    if state.get("should_fail_b"):
        return {"calls": calls, "status": "failed", "failed_step": "b"}
    return {"calls": calls}


def _node_c(state: _State) -> dict:
    return {"calls": [*(state.get("calls") or []), "c"], "status": "completed"}


def _build(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "checkpoints.db"), check_same_thread=False)
    graph = StateGraph(_State)
    for name, fn in (("a", _node_a), ("b", _node_b), ("c", _node_c)):
        graph.add_node(name, fn)
    graph.add_edge(START, "a")
    for name, nxt in (("a", "b"), ("b", "c")):
        def _router(state, _next=nxt):
            return END if state.get("status") == "failed" else _next
        graph.add_conditional_edges(name, _router, [nxt, END])
    graph.add_edge("c", END)
    return graph.compile(checkpointer=SqliteSaver(conn))


def test_update_state_as_node_reexecutes_only_the_named_nodes_successor(tmp_path):
    compiled = _build(tmp_path)
    config = {"configurable": {"thread_id": "run-1"}}

    result = compiled.invoke({"status": "running", "should_fail_b": True, "calls": []}, config=config)
    assert result["status"] == "failed"
    assert result["failed_step"] == "b"
    assert result["calls"] == ["a", "b"]

    snapshot = compiled.get_state(config)
    # A hard failure is NOT a pending interrupt — Command(resume=...) (the
    # mechanism resume_auto_pipeline/resolve_auto_run use) has nothing to
    # resume here; this is exactly why retry_auto_pipeline needs a different
    # mechanism (update_state) instead of reusing that path.
    assert not snapshot.interrupts

    values = dict(snapshot.values)
    values.update({"status": "running", "failed_step": None, "should_fail_b": False})
    compiled.update_state(config, values, as_node="a")

    result = compiled.invoke(None, config=config)

    # "b" and "c" re-ran; "a" was NOT re-executed (a full rewind to START
    # would have appended a SECOND "a" ahead of "b").
    assert result["calls"] == ["a", "b", "b", "c"]
    assert result["status"] == "completed"


def test_update_state_as_node_is_not_a_no_op(tmp_path):
    # Guards against update_state silently doing nothing (e.g. a version
    # mismatch or an as_node value langgraph doesn't recognize) — if it were
    # a no-op, invoke(None, ...) after a terminal ENDed thread would return an
    # unchanged/empty result rather than actually running "b" and "c" again.
    compiled = _build(tmp_path)
    config = {"configurable": {"thread_id": "run-2"}}
    compiled.invoke({"status": "running", "should_fail_b": True, "calls": []}, config=config)

    values = dict(compiled.get_state(config).values)
    values.update({"status": "running", "failed_step": None, "should_fail_b": False})
    compiled.update_state(config, values, as_node="a")
    result = compiled.invoke(None, config=config)

    assert result is not None
    assert result["calls"][-2:] == ["b", "c"]
