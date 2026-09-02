"""Coverage for the chat assistant's INSIGHTS intent — typing "show me
insights" (not just clicking the AssistantBot pill) resolves a target run and
hands the orchestrator's caller (routes/chat.py -> AssistantBot.jsx) an
additive `insights: {"run_id": ...}` field to fetch the PDF with, without
disturbing the existing `{reply, state, run}` shape other intents rely on.
"""

from __future__ import annotations

from backend.recon_engine import run_registry
from backend.recon_engine.chat_assistant import intent, orchestrator, session_store
from backend.recon_engine.run_registry import RunState
from backend.recon_engine.storage import pipeline_run_store

SESSION = "session-insights-intent"


def _make_active_run(graph_run_id: str) -> None:
    pipeline_run_store.create(graph_run_id)
    run_registry.transition(graph_run_id, RunState.RUNNING, reason="test setup")
    session_store.set_active_run(SESSION, graph_run_id)


def _make_stored_run(graph_run_id: str, *, name: str | None) -> None:
    pipeline_run_store.create(graph_run_id)
    run_registry.transition(graph_run_id, RunState.RUNNING, reason="test setup")
    run_registry.transition(graph_run_id, RunState.SUSPENDING, reason="test setup")
    run_registry.transition(graph_run_id, RunState.SUSPENDED, reason="test setup")
    pipeline_run_store.save_suspension(
        graph_run_id, user_name=name, suspend_reason="test setup", data_fingerprint={},
        expires_at="2999-01-01T00:00:00+00:00",
    )


def test_classify_intent_recognizes_insights_without_an_active_run():
    assert intent.classify_intent("show me insights", run_snapshot={"active_run_id": None}) == "INSIGHTS"
    assert intent.classify_intent("send the insights pdf", run_snapshot={"active_run_id": None}) == "INSIGHTS"


def test_insights_resolves_to_the_session_active_run():
    _make_active_run("autorun_insights_active_1")

    result = orchestrator.handle_message(
        message="show me insights", new_attachments=[], state=None, session_id=SESSION,
    )

    assert result["insights"] == {"run_id": "autorun_insights_active_1"}
    assert result["run"] is None


def test_insights_falls_back_to_last_completed_run_in_state():
    result = orchestrator.handle_message(
        message="show me insights", new_attachments=[],
        state={"last_completed_run_id": "autorun_insights_completed_1"}, session_id="session-insights-no-active",
    )

    assert result["insights"] == {"run_id": "autorun_insights_completed_1"}


def test_insights_resolves_a_named_stored_run():
    _make_stored_run("autorun_insights_stored_1", name="tuesday-run")

    result = orchestrator.handle_message(
        message="insights for tuesday-run", new_attachments=[], state=None, session_id="session-insights-named",
    )

    assert result["insights"] == {"run_id": "autorun_insights_stored_1"}


def test_insights_asks_which_run_when_nothing_resolves():
    result = orchestrator.handle_message(
        message="show me insights", new_attachments=[], state=None, session_id="session-insights-nothing",
    )

    assert "insights" not in result
    assert "run to build insights" in result["reply"]
