"""Coverage for the pending-confirmation gate — NEW_RUN while a run is active
must never silently replace it, an ambiguous answer must re-ask rather than
fall through to fresh classification, and a confirmed "cancel"/"suspend" must
execute the ORIGINALLY STAGED inputs (never a re-parse of the answering
message) while actually resolving run 1 (cancel -> CANCELLING, suspend ->
SUSPENDING/SUSPENDED) rather than leaving it dangling.
"""

from __future__ import annotations

import pandas as pd

from backend.recon_engine import run_registry
from backend.recon_engine.chat_assistant import orchestrator, session_store
from backend.recon_engine.run_registry import RunState
from backend.recon_engine.storage import pipeline_run_store

SESSION = "session-under-test"


def _make_active_run(graph_run_id: str) -> None:
    pipeline_run_store.create(graph_run_id)
    run_registry.transition(graph_run_id, RunState.RUNNING, reason="test setup")
    session_store.set_active_run(SESSION, graph_run_id)


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


def test_new_run_while_active_stages_a_confirmation_and_does_not_start(monkeypatch):
    _stub_reconciliation_classification(monkeypatch)
    _make_active_run("autorun_active_1")

    started = {}
    monkeypatch.setattr(
        orchestrator, "start_auto_run_from_data_state", lambda **kw: started.update(kw) or "should-not-run"
    )

    result = orchestrator.handle_message(
        message="reconcile this new data instead",
        new_attachments=[("source.csv", b"a\n1\n"), ("target.csv", b"a\n1\n")],
        state=None,
        session_id=SESSION,
    )

    assert result["run"] is None
    assert not started, "a new run must not start while a confirmation is pending"
    assert "autorun_active_1" in result["reply"]
    assert session_store.get_active_run(SESSION) == "autorun_active_1"


def test_confirming_cancel_starts_the_staged_inputs_not_the_answering_message(monkeypatch):
    _stub_reconciliation_classification(monkeypatch)
    _make_active_run("autorun_active_2")

    started = {}

    def _fake_start(**kwargs):
        started.update(kwargs)
        return "autorun_fd_replacement"

    monkeypatch.setattr(orchestrator, "start_auto_run_from_data_state", _fake_start)

    staged_reply = orchestrator.handle_message(
        message="reconcile this new data instead",
        new_attachments=[("source.csv", b"a\n1\n"), ("target.csv", b"a\n1\n")],
        state=None,
        session_id=SESSION,
    )
    assert staged_reply["run"] is None

    # The answering message itself ("cancel") would classify as nonsense if it
    # were re-parsed as a fresh reconciliation request — proving the staged
    # action, not this message, is what actually gets executed.
    result = orchestrator.handle_message(
        message="cancel", new_attachments=[], state=staged_reply["state"], session_id=SESSION
    )

    assert result["run"] == {"graph_run_id": "autorun_fd_replacement"}
    assert started["source_name"] == "source.csv"
    assert started["target_name"] == "target.csv"
    assert session_store.get_active_run(SESSION) == "autorun_fd_replacement"
    # Run 1 must actually be resolved, not just orphaned in the background.
    assert run_registry.current_state("autorun_active_2") == RunState.CANCELLING


def test_confirming_suspend_parks_run_1_and_starts_run_2(monkeypatch):
    _stub_reconciliation_classification(monkeypatch)
    _make_active_run("autorun_active_suspend")

    started = {}

    def _fake_start(**kwargs):
        started.update(kwargs)
        return "autorun_fd_replacement_2"

    monkeypatch.setattr(orchestrator, "start_auto_run_from_data_state", _fake_start)
    monkeypatch.setattr(
        orchestrator.auto_pipeline,
        "_capture_fingerprint_for",
        lambda graph_run_id: None,
    )

    staged_reply = orchestrator.handle_message(
        message="reconcile this new data instead",
        new_attachments=[("source.csv", b"a\n1\n"), ("target.csv", b"a\n1\n")],
        state=None,
        session_id=SESSION,
    )

    result = orchestrator.handle_message(
        message="suspend", new_attachments=[], state=staged_reply["state"], session_id=SESSION
    )

    assert result["run"] == {"graph_run_id": "autorun_fd_replacement_2"}
    assert started["source_name"] == "source.csv"
    # Run 1 is parked, not dangling RUNNING and not started with run 2's inputs.
    assert run_registry.current_state("autorun_active_suspend") == RunState.SUSPENDING
    assert pipeline_run_store.get_suspension("autorun_active_suspend") is not None


def test_ambiguous_answer_reasks_the_identical_question(monkeypatch):
    _stub_reconciliation_classification(monkeypatch)
    _make_active_run("autorun_active_3")
    monkeypatch.setattr(orchestrator, "start_auto_run_from_data_state", lambda **kw: "should-not-run")

    staged_reply = orchestrator.handle_message(
        message="reconcile this new data instead",
        new_attachments=[("source.csv", b"a\n1\n"), ("target.csv", b"a\n1\n")],
        state=None,
        session_id=SESSION,
    )

    result = orchestrator.handle_message(
        message="hmm not sure", new_attachments=[], state=staged_reply["state"], session_id=SESSION
    )

    assert result["reply"] == staged_reply["reply"]
    assert result["run"] is None
    # The original run is untouched by the ambiguous answer.
    assert run_registry.current_state("autorun_active_3") == RunState.RUNNING


def test_no_answer_leaves_the_active_run_running(monkeypatch):
    _stub_reconciliation_classification(monkeypatch)
    _make_active_run("autorun_active_4")
    monkeypatch.setattr(orchestrator, "start_auto_run_from_data_state", lambda **kw: "should-not-run")

    staged_reply = orchestrator.handle_message(
        message="reconcile this new data instead",
        new_attachments=[("source.csv", b"a\n1\n"), ("target.csv", b"a\n1\n")],
        state=None,
        session_id=SESSION,
    )

    result = orchestrator.handle_message(
        message="no", new_attachments=[], state=staged_reply["state"], session_id=SESSION
    )

    assert result["run"] is None
    assert run_registry.current_state("autorun_active_4") == RunState.RUNNING
    assert session_store.get_active_run(SESSION) == "autorun_active_4"


def test_a_started_runs_resolved_fields_do_not_leak_into_a_later_replace_confirmation(monkeypatch):
    """Regression: ``state`` round-trips through the frontend (see
    orchestrator.py's module docstring), and a resolved field is never
    re-asked about. Before ``_start_run_from_state`` reset ``state`` to a
    clean slate on success, a mapping-sheet run's now-consumed
    ``mapping_sheet`` reference stuck around in the state the frontend kept
    sending back — so staging a LATER, unrelated new-run request (new
    source/target attachments) captured a ``resolved_state`` still carrying
    run 1's stale mapping sheet. Since ``_start_run_from_state`` checks
    ``mapping_sheet`` first, confirming 'suspend' started run 2 from run 1's
    OLD mapping sheet instead of the newly attached source/target files."""

    def _fake_start_auto_run_state(payload):
        graph_run_id = payload["graph_run_id"]
        pipeline_run_store.create(graph_run_id)
        run_registry.transition(graph_run_id, RunState.RUNNING, reason="test setup")

    monkeypatch.setattr(
        orchestrator.intent,
        "classify",
        lambda *, message, attachment_previews: {
            "is_reconciliation": True,
            "roles": {p["filename"]: "mapping_sheet" for p in attachment_previews},
            "degraded": False,
            "degraded_reason": None,
        },
    )
    monkeypatch.setattr(
        orchestrator, "parse_mapping_sheet", lambda content, filename=None: {"headers": ["a"], "rows": [{"a": 1}]}
    )
    monkeypatch.setattr(orchestrator.registry, "get_configured_connectors", lambda: [{"kind": "sap_s4"}])
    monkeypatch.setattr(orchestrator, "live_entity_catalog", lambda kinds: ({}, []))
    monkeypatch.setattr(
        orchestrator,
        "identify_systems",
        lambda parsed, entity_catalog: {"source": {"kind": "sap_s4"}, "target": {"kind": "sap_ibp"}},
    )
    monkeypatch.setattr(orchestrator, "start_auto_run_state", _fake_start_auto_run_state)
    monkeypatch.setattr(pipeline_run_store, "new_graph_run_id", lambda: "autorun_mapping_1")

    run1_reply = orchestrator.handle_message(
        message="reconcile using this mapping sheet",
        new_attachments=[("mapping.xlsx", b"whatever")],
        state=None,
        session_id=SESSION,
    )
    assert run1_reply["run"] == {"graph_run_id": "autorun_mapping_1"}
    # The state handed back to the frontend must be a clean slate — not still
    # pointing at run 1's now-consumed mapping sheet.
    assert run1_reply["state"] == orchestrator._empty_state()

    _stub_reconciliation_classification(monkeypatch)
    monkeypatch.setattr(
        orchestrator.auto_pipeline, "_capture_fingerprint_for", lambda graph_run_id: None
    )
    started_run_2 = {}
    monkeypatch.setattr(
        orchestrator,
        "start_auto_run_from_data_state",
        lambda **kw: started_run_2.update(kw) or "autorun_mapping_2",
    )

    staged_reply = orchestrator.handle_message(
        message="reconcile these instead",
        new_attachments=[("Source_S4_Sample.xlsx", b"a\n1\n"), ("Target_IBP_Sample.xlsx", b"a\n1\n")],
        state=run1_reply["state"],
        session_id=SESSION,
    )
    assert staged_reply["run"] is None
    # The confirmation must never have captured run 1's leftover mapping sheet.
    assert staged_reply["state"]["mapping_sheet"] is None

    result = orchestrator.handle_message(
        message="suspend", new_attachments=[], state=staged_reply["state"], session_id=SESSION
    )

    assert result["run"] == {"graph_run_id": "autorun_mapping_2"}
    assert started_run_2["source_name"] == "Source_S4_Sample.xlsx"
    assert started_run_2["target_name"] == "Target_IBP_Sample.xlsx"
    assert run_registry.current_state("autorun_mapping_1") == RunState.SUSPENDING
    assert pipeline_run_store.get_suspension("autorun_mapping_1") is not None


def test_cancel_transitions_the_active_run_to_cancelling(monkeypatch):
    _make_active_run("autorun_to_cancel")

    result = orchestrator.handle_message(
        message="please cancel this run", new_attachments=[], state=None, session_id=SESSION
    )

    assert result["run"] == {"graph_run_id": "autorun_to_cancel"}
    assert run_registry.current_state("autorun_to_cancel") == RunState.CANCELLING
