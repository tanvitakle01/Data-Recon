"""LLM-based date/quantity business-key role detection for the chat/"from
data" Auto-mode path (identify_candidate_keys onwards, entered with two
already-uploaded files instead of a live SAP/IBP connector — see
``graph_from_data.py``).

The live-connector Auto-mode path (``nodes.py``'s ``_do_pair_values``) detects
these same two roles deterministically via ``field_roles.detect_roles_for_columns``
— a fixed alias list, by design, for that path (SAP/IBP naming conventions are
known and stable). Chat-uploaded files carry no such guarantee: real-world
exports use abbreviated/inconsistent headers (``Req.Dlv.Dt``, ``KEYFIGUREDATE``,
``ReqDlvQty``, ``SALESORDERREQUEST``) that a fixed alias list will keep missing.
This module asks the LLM instead, the same way ``candidate_keys.py`` already
does for product/location — except it also shows a few actual SAMPLE ROWS
(not just column names) as evidence, since a column's real values (does it
parse as a date? is it a plain numeric quantity, not a price/percentage?) are
often the only reliable signal for an unfamiliar naming convention.

Same safety posture as ``candidate_keys.py``: goes through
``build_llm_client()``, never raises on failure (degrades), and every field
name returned is existence-gated against the real column lists before use.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from backend.recon_engine.config import get_settings
from backend.recon_engine.llm import build_llm_client, get_last_llm_outcome

logger = logging.getLogger("recon.business_key_roles")

_ROLES = ("date", "quantity")
_CONFIDENCE_VALUES = ("high", "medium", "low")

_SYSTEM_PREAMBLE = """You identify BUSINESS-KEY ROLES for a data
reconciliation tool, given the REAL column names AND a few actual sample rows
from a source dataset and a target dataset (already fetched — every name and
value you see is real, not a guess).

Identify, independently for the source columns and the target columns, which
ONE column plays each of these two roles:
  - "date"     : a transaction/period/delivery date or timestamp.
  - "quantity" : a numeric quantity/amount being reconciled (requested
                 quantity, order quantity, sales quantity, etc.) — never a
                 price, currency amount, or percentage.

Column names may be abbreviated or system-specific (e.g. "Req.Dlv.Dt",
"KEYFIGUREDATE", "ReqDlvQty", "SALESORDERREQUEST") — when the name alone is
ambiguous, use the ACTUAL VALUES in the sample rows as your primary evidence:
a column whose values parse as dates is the date role; a column whose values
are plain numeric quantities (not prices/percentages) is the quantity role.

Every column name you output MUST be copied EXACTLY from the provided column
lists — never invent or guess a name.

Respond with a single JSON object only, no prose/markdown/code fences:
{
  "source": {
    "date":     {"field": "<exact source column or null>", "confidence": "high"|"medium"|"low", "reason": "<one line>"},
    "quantity": {"field": "<exact source column or null>", "confidence": "high"|"medium"|"low", "reason": "<one line>"}
  },
  "target": {
    "date":     {"field": "<exact target column or null>", "confidence": "high"|"medium"|"low", "reason": "<one line>"},
    "quantity": {"field": "<exact target column or null>", "confidence": "high"|"medium"|"low", "reason": "<one line>"}
  }
}
If you cannot confidently identify a role on a side, set its "field" to null
and "confidence" to "low" rather than guessing.
"""


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _degraded(reason: str) -> dict[str, Any]:
    empty_side = {role: {"field": None, "confidence": "low", "reason": ""} for role in _ROLES}
    return {
        "source": dict(empty_side),
        "target": dict(empty_side),
        "degraded": True,
        "degraded_reason": reason,
        "provider": None,
    }


def _gate_side(raw: Any, columns: list[str]) -> dict[str, Any]:
    lookup = {_norm(c): c for c in columns}
    exact = set(columns)
    raw = raw if isinstance(raw, dict) else {}
    out: dict[str, Any] = {}
    for role in _ROLES:
        entry = raw.get(role) if isinstance(raw.get(role), dict) else {}
        field_raw = str(entry.get("field") or "").strip()
        field = field_raw if field_raw in exact else lookup.get(_norm(field_raw))
        confidence = str(entry.get("confidence") or "low").strip().lower()
        if confidence not in _CONFIDENCE_VALUES:
            confidence = "low"
        out[role] = {
            "field": field,
            "confidence": confidence if field else "low",
            "reason": str(entry.get("reason") or "").strip(),
        }
    return out


def identify_business_key_roles(
    source_columns: list[str],
    target_columns: list[str],
    source_sample_rows: list[dict[str, Any]],
    target_sample_rows: list[dict[str, Any]],
    mapping_sheet_context: Any = None,
) -> dict[str, Any]:
    """Identify date/quantity business-key roles on each side (LLM, gated on
    both column names and a few real sample rows).

    Never raises on LLM failure: returns a ``degraded`` result. Every
    non-null ``field`` returned is guaranteed to exist verbatim in the
    corresponding column list passed in.
    """
    if not get_settings().any_llm_configured:
        return _degraded(
            "No AI provider is configured (GROQ_API_KEY / OPENAI_API_KEY) — "
            "cannot identify business-key roles."
        )
    if not source_columns or not target_columns:
        return _degraded("Source or target has no columns to identify business-key roles from.")

    user_payload: dict[str, Any] = {
        "source_columns": list(source_columns),
        "source_sample_rows": source_sample_rows,
        "target_columns": list(target_columns),
        "target_sample_rows": target_sample_rows,
    }
    if mapping_sheet_context:
        user_payload["mapping_sheet_context"] = mapping_sheet_context

    try:
        client = build_llm_client()
        payload = client.complete_json(
            [
                {"role": "system", "content": _SYSTEM_PREAMBLE},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, default=str)},
            ]
        )
    except Exception as exc:  # noqa: BLE001 — degradation is the contract
        logger.warning("Business-key role identification failed; degrading. %s", exc)
        return _degraded(f"AI business-key role identification failed: {exc}")

    if not isinstance(payload, dict):
        return _degraded("AI returned an unexpected response for business-key role identification.")

    outcome = get_last_llm_outcome()
    return {
        "source": _gate_side(payload.get("source"), source_columns),
        "target": _gate_side(payload.get("target"), target_columns),
        "degraded": False,
        "degraded_reason": None,
        "provider": (outcome.provider_used if outcome and outcome.provider_used else None),
    }
