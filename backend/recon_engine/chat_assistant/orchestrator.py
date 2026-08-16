"""Chatbot reconciliation orchestrator — the state machine described in the
plan: classify intent + attachment roles, then route into whichever existing
Auto-mode pipeline entry point the resolved state calls for.

``state`` is a small, frontend-persisted dict (no server-side chat session
store, consistent with the rest of this codebase's stateless routes):

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
from backend.recon_engine.chat_assistant import attachment_store, intent
from backend.recon_engine.mapping_sheet_parser import parse_mapping_sheet
from backend.recon_engine.sheet_identifier import identify_systems
from backend.recon_engine.storage import pipeline_run_store
from backend.routes.auto_pipeline import start_auto_run_from_data_state, start_auto_run_state
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


def handle_message(
    *,
    message: str,
    new_attachments: list[tuple[str, bytes]],
    state: dict[str, Any] | None,
) -> dict[str, Any]:
    """Returns ``{"reply": str, "state": dict, "run": {"graph_run_id": str} | None}``."""
    state = dict(state) if state else _empty_state()
    for key in ("operation", "mapping_sheet", "source_data", "target_data"):
        state.setdefault(key, None)

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
            "reply": (
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
            "reply": (
                "Hi! I'm the reconciliation assistant — ask me to reconcile a mapping sheet or "
                "a source/target dataset and I'll take it from there."
            ),
            "state": state,
            "run": None,
        }

    if state["mapping_sheet"]:
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
            return {"reply": _missing_data_reply(state), "state": state, "run": None}

        initial_state = {
            "actor": "chat",
            "comparison_type": None,
            "mapping_sheet": parsed,
            "identification": {"source": identification["source"], "target": identification["target"]},
        }
        graph_run_id = pipeline_run_store.new_graph_run_id()
        start_auto_run_state({**initial_state, "graph_run_id": graph_run_id})
        return {
            "reply": "Got it — running reconciliation from your mapping sheet now.",
            "state": state,
            "run": {"graph_run_id": graph_run_id},
        }

    if state["source_data"] and state["target_data"]:
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
        return {
            "reply": "Got it — running reconciliation on your source and target data now.",
            "state": state,
            "run": {"graph_run_id": graph_run_id},
        }

    return {"reply": _missing_data_reply(state), "state": state, "run": None}
