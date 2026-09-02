"""Coverage for two chat-assistant features layered on top of the pending-
confirmation gate (see ``test_chat_confirmation_gate.py``):

* the post-suspend "want to name it?" follow-up, answered by the session's
  very NEXT message without blocking the replacement run that already
  started; and
* resuming a STORED (suspended) run by name, run_id, or a relative time
  reference, never guessing when more than one stored run matches.
"""

from __future__ import annotations

import pandas as pd

from backend.recon_engine import run_registry
from backend.recon_engine.chat_assistant import orchestrator, session_store
from backend.recon_engine.run_registry import RunState
from backend.recon_engine.storage import pipeline_run_store

SESSION = "session-resume-naming"


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
        graph_run_id,
        user_name=name,
        suspend_reason="test setup",
        data_fingerprint={},
        expires_at="2999-01-01T00:00:00+00:00",
    )


def _stub_reconciliation_classification(monkeypatch):
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
    monkeypatch.setattr(orchestrator, "load_tabular", lambda content, name: pd.DataFrame({"a": [1]}))


def _fake_trigger_resume(graph_run_id: str, *, force: bool = False) -> dict:
    """Stand-in for ``auto_pipeline.trigger_resume`` — the real function
    schedules a background asyncio task, which needs a running event loop
    these synchronous orchestrator tests don't have. Its own DB/state-machine
    behavior is already covered by ``test_suspend_resume.py``; here we only
    need the side effects the orchestrator's resume path depends on. Does NOT
    delete the suspension row — the real ``trigger_resume`` no longer does
    either, since Stored Runs now tracks a run through resume/completion until
    the user explicitly deletes it (see ``list_stored_runs``)."""
    run_registry.transition(graph_run_id, RunState.RUNNING, reason="test resume")
    return {"graph_run_id": graph_run_id, "status": "resuming"}


# ── post-suspend naming follow-up ────────────────────────────────────────────


def test_suspend_asks_for_a_name_and_a_later_name_reply_renames_it(monkeypatch):
    _stub_reconciliation_classification(monkeypatch)
    _make_active_run("autorun_to_suspend_1")
    monkeypatch.setattr(
        orchestrator, "start_auto_run_from_data_state", lambda **kw: "autorun_replacement_1"
    )
    monkeypatch.setattr(orchestrator.auto_pipeline, "_capture_fingerprint_for", lambda graph_run_id: None)

    staged_reply = orchestrator.handle_message(
        message="reconcile this new data instead",
        new_attachments=[("source.csv", b"a\n1\n"), ("target.csv", b"a\n1\n")],
        state=None,
        session_id=SESSION,
    )
    suspend_reply = orchestrator.handle_message(
        message="suspend", new_attachments=[], state=staged_reply["state"], session_id=SESSION
    )

    # Run 2 already started — naming must not have blocked it.
    assert suspend_reply["run"] == {"graph_run_id": "autorun_replacement_1"}
    assert "name" in suspend_reply["reply"].lower()
    assert session_store.get_pending_name_prompt(SESSION) == "autorun_to_suspend_1"

    name_reply = orchestrator.handle_message(
        message="Q3 close check", new_attachments=[], state=suspend_reply["state"], session_id=SESSION
    )

    assert name_reply["run"] is None
    assert "Q3 close check" in name_reply["reply"]
    assert pipeline_run_store.get_suspension("autorun_to_suspend_1")["user_name"] == "Q3 close check"
    assert session_store.get_pending_name_prompt(SESSION) is None


def test_declining_the_name_prompt_leaves_the_run_identifiable_by_id(monkeypatch):
    _stub_reconciliation_classification(monkeypatch)
    _make_active_run("autorun_to_suspend_2")
    monkeypatch.setattr(
        orchestrator, "start_auto_run_from_data_state", lambda **kw: "autorun_replacement_2"
    )
    monkeypatch.setattr(orchestrator.auto_pipeline, "_capture_fingerprint_for", lambda graph_run_id: None)

    staged_reply = orchestrator.handle_message(
        message="reconcile this new data instead",
        new_attachments=[("source.csv", b"a\n1\n"), ("target.csv", b"a\n1\n")],
        state=None,
        session_id=SESSION,
    )
    suspend_reply = orchestrator.handle_message(
        message="suspend", new_attachments=[], state=staged_reply["state"], session_id=SESSION
    )

    decline_reply = orchestrator.handle_message(
        message="skip", new_attachments=[], state=suspend_reply["state"], session_id=SESSION
    )

    assert decline_reply["run"] is None
    before = pipeline_run_store.get_suspension("autorun_to_suspend_2")
    assert before["user_name"]  # still has its auto-generated default name, left untouched
    assert session_store.get_pending_name_prompt(SESSION) is None
    # Still resumable by run_id despite declining the name.
    assert pipeline_run_store.get(before["graph_run_id"])["status"] == RunState.SUSPENDING.value


def test_a_new_attachment_drops_the_pending_name_prompt_instead_of_hijacking_it(monkeypatch):
    _stub_reconciliation_classification(monkeypatch)
    _make_active_run("autorun_to_suspend_3")
    monkeypatch.setattr(
        orchestrator, "start_auto_run_from_data_state", lambda **kw: "autorun_replacement_3"
    )
    monkeypatch.setattr(orchestrator.auto_pipeline, "_capture_fingerprint_for", lambda graph_run_id: None)

    staged_reply = orchestrator.handle_message(
        message="reconcile this new data instead",
        new_attachments=[("source.csv", b"a\n1\n"), ("target.csv", b"a\n1\n")],
        state=None,
        session_id=SESSION,
    )
    suspend_reply = orchestrator.handle_message(
        message="suspend", new_attachments=[], state=staged_reply["state"], session_id=SESSION
    )
    assert session_store.get_pending_name_prompt(SESSION) == "autorun_to_suspend_3"

    # The session moves straight on to a THIRD request instead of answering.
    third_reply = orchestrator.handle_message(
        message="reconcile these too",
        new_attachments=[("source2.csv", b"a\n1\n"), ("target2.csv", b"a\n1\n")],
        state=suspend_reply["state"],
        session_id=SESSION,
    )

    assert session_store.get_pending_name_prompt(SESSION) is None
    # It must have been treated as a normal NEW_RUN request (staged behind
    # run 2, the session's now-active run), not consumed as a run name.
    assert pipeline_run_store.get_suspension("autorun_to_suspend_3")["user_name"] != "reconcile these too"


# ── resume by identifier ─────────────────────────────────────────────────────


def test_resume_by_exact_run_id_with_no_active_run(monkeypatch):
    monkeypatch.setattr(orchestrator.auto_pipeline, "trigger_resume", _fake_trigger_resume)
    _make_stored_run("autorun_stored_a", name=None)

    result = orchestrator.handle_message(
        message="resume autorun_stored_a", new_attachments=[], state=None, session_id=SESSION
    )

    assert result["run"] == {"graph_run_id": "autorun_stored_a"}
    assert session_store.get_active_run(SESSION) == "autorun_stored_a"
    assert pipeline_run_store.get("autorun_stored_a")["status"] == RunState.RUNNING.value


def test_resume_by_exact_name_with_no_active_run(monkeypatch):
    monkeypatch.setattr(orchestrator.auto_pipeline, "trigger_resume", _fake_trigger_resume)
    _make_stored_run("autorun_stored_b", name="Weekly IBP Check")

    result = orchestrator.handle_message(
        message="resume Weekly IBP Check", new_attachments=[], state=None, session_id=SESSION
    )

    assert result["run"] == {"graph_run_id": "autorun_stored_b"}


def test_resume_by_name_while_another_run_is_active_goes_through_confirmation(monkeypatch):
    monkeypatch.setattr(orchestrator.auto_pipeline, "trigger_resume", _fake_trigger_resume)
    monkeypatch.setattr(orchestrator.auto_pipeline, "_capture_fingerprint_for", lambda graph_run_id: None)
    _make_active_run("autorun_currently_active")
    _make_stored_run("autorun_stored_c", name="Month End")

    staged = orchestrator.handle_message(
        message="resume Month End", new_attachments=[], state=None, session_id=SESSION
    )
    assert staged["run"] is None
    assert "autorun_currently_active" in staged["reply"]

    result = orchestrator.handle_message(
        message="suspend", new_attachments=[], state=staged["state"], session_id=SESSION
    )

    assert result["run"] == {"graph_run_id": "autorun_stored_c"}
    assert run_registry.current_state("autorun_currently_active") == RunState.SUSPENDING
    # The resume path also gets the post-suspend naming follow-up.
    assert session_store.get_pending_name_prompt(SESSION) == "autorun_currently_active"


def test_resume_with_no_match_says_so_and_starts_nothing(monkeypatch):
    called = {"trigger_resume": False}
    monkeypatch.setattr(
        orchestrator.auto_pipeline,
        "trigger_resume",
        lambda *a, **kw: called.update(trigger_resume=True),
    )

    result = orchestrator.handle_message(
        message="resume nonexistent-run-xyz", new_attachments=[], state=None, session_id=SESSION
    )

    assert result["run"] is None
    assert not called["trigger_resume"]
    assert "nonexistent-run-xyz" in result["reply"]


# ── acknowledging a resume that happened OUTSIDE chat ───────────────────────


def test_status_mentions_a_run_resumed_from_the_stored_runs_tab(monkeypatch):
    """A run resumed via the Stored Runs tab's Resume button (never through
    chat at all — this session's active_run_id was never set for it) must
    still be acknowledged, with a timestamp, the next time chat is asked
    about it — see routes.auto_pipeline.trigger_resume's ``source`` param."""
    _make_stored_run("autorun_resumed_from_ui", name="Nightly Check")
    # What POST /{id}/resume does at the state-machine level, with
    # source="stored_runs_tab" — never touching chat's session/active-run
    # state, exactly like the real HTTP route.
    run_registry.transition("autorun_resumed_from_ui", RunState.RUNNING, reason="resume:stored_runs_tab")

    result = orchestrator.handle_message(
        message="status on Nightly Check", new_attachments=[], state=None, session_id=SESSION
    )

    assert "Stored Runs tab" in result["reply"]
    assert "autorun_resumed_from_ui" in result["reply"]


def test_status_says_nothing_about_a_run_resumed_from_chat_itself(monkeypatch):
    """A resume triggered BY chat already told the user in that same turn —
    repeating it on the next status check would be redundant."""
    monkeypatch.setattr(orchestrator.auto_pipeline, "trigger_resume", _fake_trigger_resume)
    _make_stored_run("autorun_resumed_from_chat", name=None)

    orchestrator.handle_message(
        message="resume autorun_resumed_from_chat", new_attachments=[], state=None, session_id=SESSION
    )
    result = orchestrator.handle_message(
        message="status", new_attachments=[], state=None, session_id=SESSION
    )

    assert "Stored Runs tab" not in result["reply"]


def test_resume_by_ambiguous_time_reference_lists_matches_instead_of_guessing(monkeypatch):
    called = {"trigger_resume": False}
    monkeypatch.setattr(
        orchestrator.auto_pipeline,
        "trigger_resume",
        lambda *a, **kw: called.update(trigger_resume=True),
    )
    _make_stored_run("autorun_morning_1", name="Run A")
    _make_stored_run("autorun_morning_2", name="Run B")

    result = orchestrator.handle_message(
        message="resume the run from this morning", new_attachments=[], state=None, session_id=SESSION
    )

    assert result["run"] is None
    assert not called["trigger_resume"]
    assert "autorun_morning_1" in result["reply"]
    assert "autorun_morning_2" in result["reply"]
