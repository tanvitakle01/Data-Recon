"""Chatbot reconciliation orchestrator — the state machine described in the
plan: intercept a pending confirmation first, then classify run-mutating
intent (CANCEL/RETRY/STATUS) deterministically against the session's current
run, and only then classify attachment roles, then route into whichever
existing Auto-mode pipeline entry point the resolved state calls for.

``state`` is a small, frontend-persisted dict — attachment-resolution
progress only (mapping sheet / source / target roles for the CURRENT
in-progress reconciliation request). It carries no run identity and is not
what gates a second run: that's ``session_id``, resolved server-side to at
most one active run via ``chat_assistant.session_store``, with any pending
"replace it?" confirmation held in ``chat_assistant.confirmation_store``.

    {"operation": "reconciliation" | None,
     "mapping_sheet": {"filename": str, "file_id": str} | None,
     "source_data": {"filename": str, "file_id": str} | None,
     "target_data": {"filename": str, "file_id": str} | None}

Each field, once resolved, is never re-asked about in a later turn — new
attachments only ever fill in whatever is still ``None``.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.API_conn.connectors import registry
from backend.excel_comparator.core.loader import load_tabular
from backend.recon_engine import run_registry
from backend.recon_engine.chat_assistant import (
    attachment_store,
    confirmation_store,
    intent,
    session_store,
    stored_run_lookup,
)
from backend.recon_engine.mapping_sheet_parser import parse_mapping_sheet
from backend.recon_engine.run_registry import RunState
from backend.recon_engine.sheet_identifier import identify_systems
from backend.recon_engine.storage import pipeline_run_store
from backend.routes import auto_pipeline
from backend.routes.auto_pipeline import (
    start_auto_run_from_data_state,
    start_auto_run_state,
    trigger_suspend,
)
from backend.routes.entity_join import live_entity_catalog

logger = logging.getLogger("recon.chat_assistant.orchestrator")

_ROLE_TO_STATE_KEY = {
    "mapping_sheet": "mapping_sheet",
    "source_data": "source_data",
    "target_data": "target_data",
}


def _empty_state() -> dict[str, Any]:
    return {"operation": None, "mapping_sheet": None, "source_data": None, "target_data": None}


def _preview(filename: str, content: bytes) -> dict[str, Any] | None:
    """Cheap classification preview: headers + first populated row. Reuses
    the mapping-sheet parser purely for its generic tabular extraction —
    works the same whether the file turns out to be a mapping sheet or plain
    source/target data. Returns None (never raises) if the file can't be
    parsed at all, so one bad attachment doesn't crash the whole turn."""
    try:
        parsed = parse_mapping_sheet(content, filename=filename)
    except Exception as exc:  # noqa: BLE001 - one bad attachment shouldn't crash the turn
        logger.warning("Could not preview chat attachment %r: %s", filename, exc)
        return None
    return {
        "filename": filename,
        "headers": parsed.get("headers") or [],
        "first_row": (parsed.get("rows") or [{}])[0],
    }


def _missing_data_reply(state: dict[str, Any]) -> str:
    have = [k for k in ("mapping_sheet", "source_data", "target_data") if state.get(k)]
    if not have:
        return (
            "I can help reconcile your data, but I don't have anything to work with yet. "
            "Attach a mapping sheet (describing which fields/systems to compare), or both "
            "a source dataset and a target dataset (CSV/Excel)."
        )
    if state.get("mapping_sheet") and not (state.get("source_data") and state.get("target_data")):
        # Mapping sheet alone is sufficient (it identifies live connectors) —
        # this branch is only reached if identification itself came back
        # unresolved; see handle_message.
        return (
            "I found a mapping sheet, but couldn't identify which configured source/target "
            "systems it describes. Please check the sheet names a system this app has "
            "connectors for, or attach the source and target data directly instead."
        )
    missing_side = "target" if state.get("source_data") else "source"
    return (
        f"I have your {'source' if missing_side == 'target' else 'target'} data, but still need "
        f"the {missing_side} dataset (CSV/Excel) to run a reconciliation."
    )


def _active_run_id(session_id: str) -> str | None:
    """The session's active run, if it's still genuinely active — a stale
    binding (the run finished, or FAILED without being retried, since the
    session was last seen) is cleared here rather than left to block a
    fresh NEW_RUN forever."""
    active_run_id = session_store.get_active_run(session_id)
    if active_run_id is None:
        return None
    try:
        if run_registry.is_active(active_run_id):
            return active_run_id
    except ValueError:
        pass
    session_store.set_active_run(session_id, None)
    return None


def _status_reply(run_id: str) -> str:
    run = pipeline_run_store.get(run_id)
    if run is None:
        return f"I don't have any record of run {run_id} anymore."
    status = run.get("status")
    step = run.get("current_step")
    if status == RunState.PAUSED_FOR_INPUT.value:
        return f"Run {run_id} is waiting on your answer to a question I asked earlier."
    if status == RunState.STALLED.value:
        return f"Run {run_id} looks stalled — it hasn't reported progress in a while. It's still being watched."
    if status == RunState.CANCELLING.value:
        return f"Run {run_id} is being cancelled."
    if status == RunState.RUNNING.value:
        return f"Run {run_id} is still running" + (f" (currently on '{step}')." if step else ".")
    return f"Run {run_id} is currently {status!r}."


def _start_run_from_state(state: dict[str, Any], *, session_id: str, prefix: str = "") -> dict[str, Any]:
    """Actually starts a reconciliation from a fully-resolved ``state`` —
    shared by the normal NEW_RUN path and a confirmed "yes" on a staged
    ``start_new_run`` action (which passes the EXACT ``state`` captured at
    stage-time, never a re-derivation of the current message)."""
    if state.get("mapping_sheet"):
        filename, content = attachment_store.load(state["mapping_sheet"]["file_id"])
        parsed = parse_mapping_sheet(content, filename=filename)
        kinds = [c["kind"] for c in registry.get_configured_connectors()]
        catalog, catalog_warnings = live_entity_catalog(kinds)
        identification = identify_systems(parsed, entity_catalog=catalog)
        if catalog_warnings:
            identification["warnings"] = [*identification.get("warnings", []), *catalog_warnings]

        if (
            identification.get("degraded")
            or not identification.get("source", {}).get("kind")
            or not identification.get("target", {}).get("kind")
        ):
            return {"reply": prefix + _missing_data_reply(state), "state": state, "run": None}

        initial_state = {
            "actor": "chat",
            "comparison_type": None,
            "mapping_sheet": parsed,
            "identification": {"source": identification["source"], "target": identification["target"]},
        }
        graph_run_id = pipeline_run_store.new_graph_run_id()
        start_auto_run_state({**initial_state, "graph_run_id": graph_run_id})
        session_store.set_active_run(session_id, graph_run_id)
        return {
            "reply": prefix + "Got it — running reconciliation from your mapping sheet now.",
            # Reset to a clean slate now that these inputs have been consumed
            # into a run — leaving the resolved fields in place would let a
            # LATER, unrelated request's attachments get silently gated behind
            # (or worse, overridden by) this run's already-used mapping sheet,
            # since a resolved field is never re-asked about (see module
            # docstring). This is what a run being replaced from confirmation
            # must never inherit.
            "state": _empty_state(),
            "run": {"graph_run_id": graph_run_id},
        }

    if state.get("source_data") and state.get("target_data"):
        source_name, source_content = attachment_store.load(state["source_data"]["file_id"])
        target_name, target_content = attachment_store.load(state["target_data"]["file_id"])
        source_df = load_tabular(source_content, source_name)
        target_df = load_tabular(target_content, target_name)

        graph_run_id = start_auto_run_from_data_state(
            source_df=source_df,
            target_df=target_df,
            source_name=source_name,
            target_name=target_name,
            actor="chat",
        )
        session_store.set_active_run(session_id, graph_run_id)
        return {
            "reply": prefix + "Got it — running reconciliation on your source and target data now.",
            "state": _empty_state(),  # see the mapping-sheet branch above
            "run": {"graph_run_id": graph_run_id},
        }

    return {"reply": prefix + _missing_data_reply(state), "state": state, "run": None}


def _resume_stored_run(graph_run_id: str, *, session_id: str, prefix: str = "") -> dict[str, Any]:
    """Unparks a SUSPENDED run — the chat-side counterpart of
    ``POST /{id}/resume``, reusing ``trigger_resume`` directly rather than
    duplicating its fingerprint-staleness/background-kickoff logic."""
    try:
        auto_pipeline.trigger_resume(graph_run_id)
    except ValueError:
        return {
            "reply": prefix + (
                f"Run {graph_run_id}'s source/target data looks like it has changed since it was "
                "suspended, so I didn't resume it automatically to avoid mixing two data vintages. "
                "Discard it and start fresh, or check with whoever manages that connection."
            ),
            "state": _empty_state(),
            "run": None,
        }
    session_store.set_active_run(session_id, graph_run_id)
    return {
        "reply": prefix + f"Resuming run {graph_run_id} from where it left off.",
        "state": _empty_state(),
        "run": {"graph_run_id": graph_run_id},
    }


def _format_stored_run_option(suspension: dict[str, Any]) -> str:
    label = suspension["user_name"] or "(unnamed)"
    return f"- {label} — run {suspension['graph_run_id']}, suspended {suspension['suspended_at']}"


def _handle_resume_query(
    query: str, *, session_id: str, active_run_id: str | None, state: dict[str, Any], prefix: str
) -> dict[str, Any]:
    """Resolves a "resume <identifier>" chat request (see
    ``intent.parse_resume_stored_query``) against Stored Runs. Never guesses:
    zero matches says so plainly, more than one lists every candidate and
    asks which, and exactly one goes through the same cancel/suspend/no
    confirmation gate as NEW_RUN when another run is currently active."""
    matches = stored_run_lookup.find(query)
    if not matches:
        return {
            "reply": prefix + f"I couldn't find a stored run matching {query!r}.",
            "state": state,
            "run": None,
        }
    if len(matches) > 1:
        options = "\n".join(_format_stored_run_option(m) for m in matches)
        return {
            "reply": prefix + f"I found more than one stored run matching that — which one?\n{options}",
            "state": state,
            "run": None,
        }

    target_run_id = matches[0]["graph_run_id"]
    if active_run_id is not None:
        question = (
            f"Resuming run {target_run_id} ({matches[0]['user_name'] or 'unnamed'}) means replacing "
            f"your current run ({active_run_id}). Reply 'cancel' to cancel it and resume the stored "
            "run, 'suspend' to pause it and resume the stored run, or 'no' to keep the current run going."
        )
        confirmation_store.stage(
            session_id,
            question=question,
            staged_action={"resume_graph_run_id": target_run_id, "active_run_id": active_run_id},
            target_run_ids=[active_run_id],
        )
        return {"reply": prefix + question, "state": state, "run": None}

    return _resume_stored_run(target_run_id, session_id=session_id, prefix=prefix)


def _execute_staged_action(staged_action: dict[str, Any], *, session_id: str) -> dict[str, Any]:
    """Concurrent runs are never supported — exactly two choices ever reach
    here: discard run 1 (CANCELLING, cooperatively resolves to CANCELLED) or
    park it (SUSPENDING, resumable later from Stored Runs), either way
    followed by starting run 2 — either from ITS OWN ``resolved_state`` (the
    ORIGINALLY BOUND inputs captured at stage-time — never a re-parse of
    whatever the choice message itself happens to say) or, for a staged
    "resume a stored run" action, by unparking that stored run instead."""
    action_type = staged_action.get("type")
    active_run_id = staged_action.get("active_run_id")
    prefix = ""
    suspended_successfully = False

    if action_type == "cancel_and_start":
        run_registry.transition(active_run_id, RunState.CANCELLING, reason="replaced by new chat request")
        prefix = f"Cancelling run {active_run_id}. "
    elif action_type == "suspend_and_start":
        try:
            trigger_suspend(active_run_id, reason="replaced by new chat request")
            prefix = f"Suspended run {active_run_id} — find it later under Stored Runs. "
            suspended_successfully = True
        except run_registry.IllegalTransition:
            # Run 1 isn't in a suspendable state right now (e.g. it's
            # waiting on a resolver-bot answer) — fall back to cancel rather
            # than silently doing nothing to it while still starting run 2.
            run_registry.transition(active_run_id, RunState.CANCELLING, reason="replaced by new chat request")
            prefix = f"Run {active_run_id} couldn't be suspended right now, so it was cancelled instead. "
    else:
        return {
            "reply": "Something went wrong resolving that confirmation — please try again.",
            "state": _empty_state(),
            "run": None,
        }

    if "resume_graph_run_id" in staged_action:
        result = _resume_stored_run(staged_action["resume_graph_run_id"], session_id=session_id, prefix=prefix)
    else:
        result = _start_run_from_state(staged_action["resolved_state"], session_id=session_id, prefix=prefix)

    if suspended_successfully:
        # Ask for an optional name, but never gate run 2 (already started
        # above) on the answer — the next message this session sends is
        # interpreted as that answer by the pending-name-prompt gate in
        # handle_message, unless it turns out to carry new attachments of
        # its own, in which case the prompt is dropped rather than hijacking
        # that message.
        session_store.set_pending_name_prompt(session_id, active_run_id)
        result = {
            **result,
            "reply": result["reply"]
            + " Want to give the suspended run a name so it's easier to find later? Reply with a name, or say 'skip'.",
        }
    return result


def handle_message(
    *,
    message: str,
    new_attachments: list[tuple[str, bytes]],
    state: dict[str, Any] | None,
    session_id: str,
) -> dict[str, Any]:
    """Returns ``{"reply": str, "state": dict, "run": {"graph_run_id": str} | None}``.

    ``session_id`` is the EXISTING authenticated session id (see
    ``routes/chat.py``) — the key for this session's active-run binding and
    any pending confirmation. Every message is routed through the pending-
    confirmation gate FIRST, before any intent classification at all.
    """
    # ── 1. pending-confirmation gate — intercepts BEFORE intent classification ──
    prefix = ""
    pending = confirmation_store.get_pending(session_id)
    if pending is not None:
        if pending["status"] == "expired":
            prefix = "(Your previous request timed out — please try again.) "
        else:
            resolution = intent.interpret_cancel_suspend_no(message)
            if resolution == "ambiguous":
                # Never falls through to fresh classification — re-ask the
                # identical question until it's answered with one of the
                # exactly two options (or a decline).
                return {"reply": pending["question"], "state": state or _empty_state(), "run": None}
            confirmation_store.answer(pending["confirmation_id"], resolution)
            if resolution == "no":
                return {
                    "reply": "Okay — the current run keeps going.",
                    "state": state or _empty_state(),
                    "run": None,
                }
            staged_action = {**pending["staged_action"], "type": f"{resolution}_and_start"}
            return _execute_staged_action(staged_action, session_id=session_id)

    state = dict(state) if state else _empty_state()
    for key in ("operation", "mapping_sheet", "source_data", "target_data"):
        state.setdefault(key, None)

    # ── 1.5. pending suspended-run naming follow-up ──
    # Set right after a successful suspend (see _execute_staged_action). New
    # attachments take priority over answering it — the prompt is dropped
    # silently rather than swallowing a message that's clearly moving on to
    # something else.
    pending_name_run_id = session_store.get_pending_name_prompt(session_id)
    if pending_name_run_id is not None:
        session_store.set_pending_name_prompt(session_id, None)
        if not new_attachments:
            name = intent.interpret_name_or_skip(message)
            if name:
                pipeline_run_store.set_suspension_name(pending_name_run_id, name)
                return {"reply": prefix + f"Got it — named that suspended run {name!r}.", "state": state, "run": None}
            return {
                "reply": prefix + "No problem — you can still find it later by its run ID.",
                "state": state,
                "run": None,
            }

    # ── 2. run-mutating intent, classified against THIS session's run state ──
    active_run_id = _active_run_id(session_id)

    resume_query = intent.parse_resume_stored_query(message)
    if resume_query:
        return _handle_resume_query(
            resume_query, session_id=session_id, active_run_id=active_run_id, state=state, prefix=prefix
        )

    control_intent = intent.classify_intent(message, run_snapshot={"active_run_id": active_run_id})

    if control_intent == "CANCEL":
        run_registry.transition(active_run_id, RunState.CANCELLING, reason="user requested cancel")
        return {
            "reply": prefix + f"Cancelling run {active_run_id} — it'll stop shortly.",
            "state": state,
            "run": {"graph_run_id": active_run_id},
        }

    if control_intent == "RETRY":
        if not auto_pipeline.has_resumable_checkpoint(active_run_id):
            return {
                "reply": prefix + "There's nothing resumable to retry on your current run right now.",
                "state": state,
                "run": {"graph_run_id": active_run_id},
            }
        auto_pipeline.trigger_retry(active_run_id, reason="chat retry")
        return {
            "reply": prefix + "Retrying the reconciliation from where it left off…",
            "state": state,
            "run": {"graph_run_id": active_run_id},
        }

    if control_intent == "STATUS":
        return {"reply": prefix + _status_reply(active_run_id), "state": state, "run": {"graph_run_id": active_run_id}}

    # ── 3. attachment-role / reconciliation-intent classification (LLM) ──
    # Only classify attachments this state hasn't already resolved a role
    # for — a role fixed in an earlier turn is never re-asked about.
    unresolved_names = {
        key for key in ("mapping_sheet", "source_data", "target_data") if state.get(key) is None
    }
    previews = []
    file_ids: dict[str, str] = {}
    for filename, content in new_attachments:
        file_ids[filename] = attachment_store.save(filename, content)
        preview = _preview(filename, content)
        if preview is not None:
            previews.append(preview)

    classification = intent.classify(message=message, attachment_previews=previews)

    # A degraded classification (every configured LLM provider unavailable —
    # rate-limited, misconfigured, or simply down) must never be silently
    # read as "not a reconciliation request": that's indistinguishable from
    # a real "no" to the user, when the honest answer is "couldn't check."
    # Only matters when intent for THIS conversation isn't already settled —
    # once operation is "reconciliation" from an earlier turn, a degraded
    # classification of a new attachment just leaves its role unresolved and
    # falls through to the ordinary "still missing X" reply below.
    if classification.get("degraded") and state["operation"] != "reconciliation":
        return {
            "reply": prefix + (
                "I couldn't reach the AI service just now to understand your request "
                "(every configured provider is temporarily unavailable or rate-limited). "
                "Please try again in a moment."
            ),
            "state": state,
            "run": None,
        }

    if state["operation"] != "reconciliation" and classification["is_reconciliation"]:
        state["operation"] = "reconciliation"

    for filename, role in classification["roles"].items():
        state_key = _ROLE_TO_STATE_KEY.get(role)
        if state_key is None or state_key not in unresolved_names:
            continue
        if state.get(state_key) is not None:
            continue
        state[state_key] = {"filename": filename, "file_id": file_ids[filename]}

    if state["operation"] != "reconciliation":
        return {
            "reply": prefix + (
                "Hi! I'm the reconciliation assistant — ask me to reconcile a mapping sheet or "
                "a source/target dataset and I'll take it from there."
            ),
            "state": state,
            "run": None,
        }

    # ── 4. NEW_RUN: gate on the session's active run before ever starting one ──
    # Concurrent runs are never offered — exactly two choices: discard run 1
    # (cancel) or park it for later (suspend), each followed by starting run 2
    # with its own resolved_state (see _execute_staged_action).
    ready_to_start = bool(state["mapping_sheet"]) or bool(state["source_data"] and state["target_data"])
    if ready_to_start and active_run_id is not None:
        question = (
            f"You already have a reconciliation running (run {active_run_id}). "
            "Reply 'cancel' to cancel it and start this new one, 'suspend' to pause it "
            "(resumable later from Stored Runs) and start this new one, or 'no' to keep "
            "the current run going."
        )
        confirmation_store.stage(
            session_id,
            question=question,
            staged_action={"resolved_state": state, "active_run_id": active_run_id},
            target_run_ids=[active_run_id],
        )
        return {"reply": prefix + question, "state": state, "run": None}

    if ready_to_start:
        return _start_run_from_state(state, session_id=session_id, prefix=prefix)

    return {"reply": prefix + _missing_data_reply(state), "state": state, "run": None}
