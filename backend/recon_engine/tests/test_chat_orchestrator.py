"""Chat orchestrator state machine — intent classification is faked so these
tests are deterministic; the point is the branching contract, not the model.

The degraded-classification test is a direct regression for a real incident:
every configured LLM provider (Groq rate-limited, Gemini free-tier exhausted,
Cerebras returning a 404 model-not-found) failed at once, and the assistant
silently told the user their reconciliation request "wasn't a reconciliation
request" — indistinguishable from a real "no" when the honest answer was "AI
service unavailable, try again."
"""

from __future__ import annotations

import pandas as pd

from backend.recon_engine.chat_assistant import orchestrator


def test_degraded_classification_gives_an_honest_reply_not_a_false_no(monkeypatch):
    monkeypatch.setattr(
        orchestrator.intent,
        "classify",
        lambda **kwargs: {
            "is_reconciliation": False,
            "roles": {},
            "degraded": True,
            "degraded_reason": "all providers unavailable",
        },
    )

    result = orchestrator.handle_message(
        message="reconcile", new_attachments=[], state=None, session_id="test-session"
    )

    assert result["state"]["operation"] is None
    assert result["run"] is None
    assert "AI service" in result["reply"]
    assert "reconciliation assistant" not in result["reply"]  # not the generic "no" reply


def test_non_reconciliation_message_gets_the_generic_reply(monkeypatch):
    monkeypatch.setattr(
        orchestrator.intent,
        "classify",
        lambda **kwargs: {"is_reconciliation": False, "roles": {}, "degraded": False, "degraded_reason": None},
    )

    result = orchestrator.handle_message(
        message="hello", new_attachments=[], state=None, session_id="test-session"
    )

    assert result["state"]["operation"] is None
    assert result["run"] is None
    assert "reconciliation assistant" in result["reply"]


def test_reconciliation_intent_with_no_files_asks_for_data(monkeypatch):
    monkeypatch.setattr(
        orchestrator.intent,
        "classify",
        lambda **kwargs: {"is_reconciliation": True, "roles": {}, "degraded": False, "degraded_reason": None},
    )

    result = orchestrator.handle_message(
        message="reconcile please", new_attachments=[], state=None, session_id="test-session"
    )

    assert result["state"]["operation"] == "reconciliation"
    assert result["run"] is None
    assert "mapping sheet" in result["reply"] or "dataset" in result["reply"]


def test_source_and_target_resolved_starts_the_from_data_pipeline(monkeypatch):
    monkeypatch.setattr(
        orchestrator.intent,
        "classify",
        lambda *, message, attachment_previews: {
            "is_reconciliation": True,
            "roles": {p["filename"]: role for p, role in zip(attachment_previews, ["source_data", "target_data"])},
            "degraded": False,
            "degraded_reason": None,
        },
    )
    monkeypatch.setattr(
        orchestrator, "load_tabular", lambda content, name: pd.DataFrame({"a": [1]})
    )
    started = {}

    def _fake_start(**kwargs):
        started.update(kwargs)
        return "autorun_fd_test123"

    monkeypatch.setattr(orchestrator, "start_auto_run_from_data_state", _fake_start)

    result = orchestrator.handle_message(
        message="reconcile my source and target data",
        new_attachments=[("source.csv", b"a\n1\n"), ("target.csv", b"a\n1\n")],
        state=None,
        session_id="test-session",
    )

    assert result["run"] == {"graph_run_id": "autorun_fd_test123"}
    assert "running reconciliation" in result["reply"]
    assert started["source_name"] == "source.csv"
    assert started["target_name"] == "target.csv"


def test_already_established_operation_is_not_reopened_by_a_later_degraded_call(monkeypatch):
    """Once reconciliation intent is settled in an earlier turn, a later
    turn's degraded classification (e.g. an unrelated follow-up attachment)
    must not re-litigate whether this is a reconciliation request — it just
    falls through to whatever's still missing."""
    monkeypatch.setattr(
        orchestrator.intent,
        "classify",
        lambda **kwargs: {"is_reconciliation": False, "roles": {}, "degraded": True, "degraded_reason": "down"},
    )

    prior_state = {"operation": "reconciliation", "mapping_sheet": None, "source_data": None, "target_data": None}
    result = orchestrator.handle_message(
        message="here's more", new_attachments=[], state=prior_state, session_id="test-session"
    )

    assert result["state"]["operation"] == "reconciliation"
    assert "AI service" not in result["reply"]
