"""Chatbot intent + attachment-role classification (one LLM call).

Given the user's chat message and, for each attachment not already pinned to
a role from an earlier turn in this conversation, a cheap preview (filename +
column headers + first populated row), infer:

* whether this message is asking for a reconciliation at all, and
* which role each new attachment plays: a mapping sheet, source data, target
  data, or none of those.

Same provider as every other LLM call in this codebase (Azure-AI-Foundry-only
``build_llm_client()``, no fallback — see
``backend/recon_engine/llm/failover.py``), and the same
never-raise-degrade-instead contract as ``sheet_identifier.identify_systems``:
a provider failure returns a conservative "not enough to tell" result rather
than raising, so the chatbot always has something to say back.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal

from backend.recon_engine.llm import build_llm_client

logger = logging.getLogger("recon.chat_assistant.intent")

_ROLE_VALUES = ("mapping_sheet", "source_data", "target_data", "unknown")

RunIntent = Literal["CANCEL", "RETRY", "STATUS", "INSIGHTS", "OTHER"]

# Deterministic, not LLM — these are run-mutating or safety-relevant
# (CANCEL/RETRY act on the session's active run; STATUS must never silently
# misreport), so guessing wrong on them is exactly the "silent failure" class
# this classifier exists to prevent. An LLM call here would put the single
# routing decision behind the same "every provider unavailable" degradation
# mode the rest of this module already treats as untrustworthy for control
# flow. "OTHER" falls through to the existing LLM ``classify()`` below, which
# already distinguishes a genuine reconciliation request (NEW_RUN) from small
# talk (QUESTION) — no separate NEW_RUN/QUESTION split is needed here.
_CANCEL_KEYWORDS = ("cancel", "abort", "stop the run", "stop this run", "kill the run", "kill this run")
_RETRY_KEYWORDS = ("retry", "resume", "continue the run", "continue this run", "try again")
_STATUS_KEYWORDS = (
    "status", "progress", "how's it going", "how is it going", "what's happening",
    "is it done", "are we done", "update me",
)
# Unlike CANCEL/RETRY (which mutate a run and so only ever make sense against
# THIS session's own active run), STATUS/INSIGHTS are read-only and are most
# often asked about a run this chat session never started — most notably one
# resumed from the Stored Runs tab, which never touches active_run_id at all
# (see routes.auto_pipeline.trigger_resume's ``source`` param). Gating STATUS
# on active_run_id would make orchestrator.handle_message's own "no run bound
# to this session (e.g. resumed from the Stored Runs tab)" fallback dead code
# — so, like INSIGHTS, STATUS is checked unconditionally and the orchestrator
# resolves which run it refers to (by name/id in the message, else the
# session's active run).
_INSIGHTS_KEYWORDS = (
    "insights", "insight report", "insights pdf", "insight pdf", "show me insights",
    "generate insights", "view insights", "insights report",
)


def _matches(text: str, keywords: tuple[str, ...]) -> bool:
    return any(re.search(rf"\b{re.escape(kw)}\b" if " " not in kw else re.escape(kw), text) for kw in keywords)


def classify_intent(message: str, *, run_snapshot: dict[str, Any]) -> RunIntent:
    """Run state is an INPUT here, not consulted afterward: CANCEL/RETRY are
    only meaningful (and only checked for) when ``run_snapshot`` actually has
    an active/failed run to target — a bare "cancel" typed with nothing
    running falls through to OTHER (which resolves to a plain reply) rather
    than being misrouted as a run-mutating command with nothing to act on."""
    text = (message or "").strip().lower()
    if not text:
        return "OTHER"
    active_run_id = run_snapshot.get("active_run_id")
    if active_run_id and _matches(text, _CANCEL_KEYWORDS):
        return "CANCEL"
    if active_run_id and _matches(text, _RETRY_KEYWORDS):
        return "RETRY"
    if _matches(text, _STATUS_KEYWORDS):
        return "STATUS"
    if _matches(text, _INSIGHTS_KEYWORDS):
        return "INSIGHTS"
    return "OTHER"


_YES_WORDS = {"yes", "y", "yeah", "yep", "yup", "confirm", "confirmed", "ok", "okay", "go ahead", "do it", "sure"}
_NO_WORDS = {"no", "n", "nope", "nah", "cancel", "don't", "dont", "stop"}


def interpret_yes_no(message: str) -> Literal["yes", "no", "ambiguous"]:
    """Deterministic answer-interpretation for a pending confirmation — never
    LLM-based (see module docstring above on why control flow here must not
    depend on something that can degrade). Ambiguous text must re-ask the
    same question rather than fall through to fresh classification."""
    text = (message or "").strip().lower().rstrip(".!")
    if text in _YES_WORDS:
        return "yes"
    if text in _NO_WORDS:
        return "no"
    return "ambiguous"


_CANCEL_CHOICE_WORDS = {"cancel", "cancel it", "cancel run", "cancel and start"}
_SUSPEND_CHOICE_WORDS = {"suspend", "pause", "park", "suspend it", "suspend run", "suspend and start"}
_DECLINE_CHOICE_WORDS = _NO_WORDS | {"neither", "keep it going", "leave it running"}


def interpret_cancel_suspend_no(message: str) -> Literal["cancel", "suspend", "no", "ambiguous"]:
    """Deterministic three-way answer-interpretation for the NEW_RUN-while-
    active-run confirmation (see ``orchestrator.py``): exactly the two
    options the run-lifecycle design permits — cancel run 1 and start, or
    suspend run 1 and start — plus a decline that leaves run 1 untouched.
    Never LLM-based, same rationale as :func:`interpret_yes_no`. Ambiguous
    text must re-ask rather than fall through to fresh classification."""
    text = (message or "").strip().lower().rstrip(".!")
    if text in _CANCEL_CHOICE_WORDS:
        return "cancel"
    if text in _SUSPEND_CHOICE_WORDS:
        return "suspend"
    if text in _DECLINE_CHOICE_WORDS:
        return "no"
    return "ambiguous"


_SKIP_NAME_WORDS = _NO_WORDS | {
    "skip", "none", "no thanks", "no thank you", "not now", "never mind", "nevermind",
}


def interpret_name_or_skip(message: str) -> str | None:
    """Deterministic answer-interpretation for the post-suspend "want to name
    it?" follow-up: a name is arbitrary free text, so anything that isn't an
    explicit decline is taken verbatim as the name. Never LLM-based — same
    rationale as :func:`interpret_yes_no`."""
    text = (message or "").strip()
    if not text or text.lower().rstrip(".!") in _SKIP_NAME_WORDS:
        return None
    return text


_RESUME_STORED_PATTERN = re.compile(r"^\s*resume\b(.*)$", re.IGNORECASE)
_BARE_RESUME_PHRASES = {"", "it", "this", "this run", "the run", "current run", "the current run"}


def parse_resume_stored_query(message: str) -> str | None:
    """A bare "resume" (or "resume it"/"resume this run") means retry the
    session's own active run — see :func:`classify_intent`'s RETRY keyword,
    which still handles that case. Anything else following "resume" names a
    STORED (suspended) run to look up instead — a name, a run_id, or a time
    reference (e.g. "resume the run from this morning") — and is returned
    verbatim as the lookup query. Returns ``None`` when the message isn't a
    "resume <something>" request at all, or is one of the bare phrases
    above."""
    match = _RESUME_STORED_PATTERN.match((message or "").strip())
    if match is None:
        return None
    rest = match.group(1).strip().rstrip(".!")
    if rest.lower() in _BARE_RESUME_PHRASES:
        return None
    return rest


_SYSTEM_PREAMBLE = """You triage chat messages for a data-reconciliation
assistant. Given the user's message text and a preview of each newly
attached file (filename, column headers, and its first populated data row),
decide:

1. `is_reconciliation`: true only if the user is asking to reconcile,
   compare, or match two datasets — not a general question, greeting, or
   unrelated request.
2. `roles`: for EVERY filename given in `attachments`, classify it as exactly
   one of:
   - "mapping_sheet": a sheet whose rows describe field/entity mappings,
     join rules, or which systems/fields to compare (not transactional data
     itself) — e.g. columns like Source Field, Target Field, Join Condition,
     Transformation Notes.
   - "source_data": transactional/master data representing the SOURCE side
     of a comparison (sales orders, inventory, planning data, etc.).
   - "target_data": the same kind of data, but representing the TARGET side.
   - "unknown": you cannot tell, or it is unrelated to reconciliation.

Use the message text as the strongest signal for source vs. target ("reconcile
X against Y" implies X=source, Y=target) — if the message doesn't say, infer
from column shape: a mapping sheet's rows describe fields/mappings, not
business records; source/target data files contain actual business rows.
When two data files look alike and the message gives no ordering hint,
prefer keeping their upload order (first file = source, second = target).

Return strictly the requested JSON shape — no prose, no markdown."""


def classify(
    *,
    message: str,
    attachment_previews: list[dict[str, Any]],
) -> dict[str, Any]:
    """``attachment_previews``: ``[{"filename": str, "headers": [...], "first_row": {...}}]``
    for attachments not already pinned to a role from a prior turn.

    Returns ``{"is_reconciliation": bool, "roles": {filename: role}, "degraded": bool,
    "degraded_reason": str | None}``. Never raises — a provider failure degrades to
    ``is_reconciliation=False`` with every role "unknown", so the caller falls back
    to asking the user directly rather than crashing the chat turn.
    """
    if not message.strip() and not attachment_previews:
        return {
            "is_reconciliation": False,
            "roles": {},
            "degraded": False,
            "degraded_reason": None,
        }

    user_payload = {"message": message, "attachments": attachment_previews}

    try:
        client = build_llm_client()
        payload = client.complete_json(
            [
                {"role": "system", "content": _SYSTEM_PREAMBLE},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, default=str)},
            ]
        )
    except Exception as exc:  # noqa: BLE001 - degradation is the contract
        logger.warning("Chat intent classification failed; degrading. %s", exc)
        return {
            "is_reconciliation": False,
            "roles": {p["filename"]: "unknown" for p in attachment_previews},
            "degraded": True,
            "degraded_reason": str(exc),
        }

    if not isinstance(payload, dict):
        return {
            "is_reconciliation": False,
            "roles": {p["filename"]: "unknown" for p in attachment_previews},
            "degraded": True,
            "degraded_reason": "AI returned an unexpected response for intent classification.",
        }

    raw_roles = payload.get("roles") if isinstance(payload.get("roles"), dict) else {}
    roles = {
        p["filename"]: raw_roles.get(p["filename"])
        if raw_roles.get(p["filename"]) in _ROLE_VALUES
        else "unknown"
        for p in attachment_previews
    }

    return {
        "is_reconciliation": bool(payload.get("is_reconciliation")),
        "roles": roles,
        "degraded": False,
        "degraded_reason": None,
    }
