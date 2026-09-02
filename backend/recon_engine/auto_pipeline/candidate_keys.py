"""Stage 3 (LLM ONLY): candidate business-key identification for value pairing.

Given the REAL, already-imported, already-schema-verified columns on each
side, ask the LLM which single column is the best STRING-based business
identifier for a "product/material-like" role and for a "location/plant-like"
role — the two dimensions the value-pairing pipeline (DISTINCT extraction,
exact-match discovery, transformation discovery) operates on.

Boundary this module exists to enforce: these candidate keys are used
EXCLUSIVELY to drive value pairing. They are never used to build the
reconciliation ``business_key`` — that stays a separate, deterministic
concept sourced from the mapping sheet/business rules (see
``auto_pipeline/field_matching.py``'s date/quantity role detection, which
``business_key`` construction keeps using, independently of this module).

Same safety posture as ``sheet_identifier.py``/``field_mapper.py``: goes
through the Azure-AI-Foundry-only ``build_llm_client()`` (no fallback), never raises on
failure (degrades), and every field name the model returns is existence-gated
against the real column lists before use.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from backend.recon_engine.config import get_settings
from backend.recon_engine.llm import build_llm_client, get_last_llm_outcome

logger = logging.getLogger("recon.candidate_keys")

_ROLES = ("product", "location")

_SYSTEM_PREAMBLE = """You identify CANDIDATE BUSINESS KEYS for a data
reconciliation tool's value-pairing step, given the REAL column names actually
present in a source dataset and a target dataset (already fetched and
schema-verified — every name you see is real).

Identify, independently for the source columns and the target columns, which
ONE column is the best STRING-BASED BUSINESS IDENTIFIER for each of these two
roles:
  - "product"  : a material/product/SKU/item identifier.
  - "location" : a plant/site/facility/location identifier.

Hard rule — NEVER select a column for either role if it is a date, timestamp,
period, quantity, amount, price, currency, percentage, or any other numeric
MEASURE. Only string-based business/dimension identifiers qualify, even if
such a column happens to be numeric-looking (e.g. a zero-padded material
code) — the test is whether it identifies a business entity, not whether it
measures something.

You may optionally use the small context object (parsed mapping-sheet
excerpts, if provided) as supporting evidence, but every column name you
output MUST be copied EXACTLY from the provided column lists — never invent
or guess a name.

Respond with a single JSON object only, no prose/markdown/code fences:
{
  "source": {
    "product":  {"field": "<exact source column or null>", "confidence": "high"|"medium"|"low", "reason": "<one line>"},
    "location": {"field": "<exact source column or null>", "confidence": "high"|"medium"|"low", "reason": "<one line>"}
  },
  "target": {
    "product":  {"field": "<exact target column or null>", "confidence": "high"|"medium"|"low", "reason": "<one line>"},
    "location": {"field": "<exact target column or null>", "confidence": "high"|"medium"|"low", "reason": "<one line>"}
  }
}
If you cannot confidently identify a role on a side, set its "field" to null
and "confidence" to "low" rather than guessing.
"""

_CONFIDENCE_VALUES = ("high", "medium", "low")


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


def identify_candidate_keys(
    source_columns: list[str],
    target_columns: list[str],
    mapping_sheet_context: Any = None,
) -> dict[str, Any]:
    """Identify product/location candidate keys on each side (LLM, gated).

    Never raises on LLM failure: returns a ``degraded`` result. Every
    non-null ``field`` returned is guaranteed to exist verbatim in the
    corresponding column list passed in.
    """
    if not get_settings().any_llm_configured:
        return _degraded(
            "No AI provider is configured (AZURE_FOUNDRY_MODEL) — "
            "cannot identify candidate keys."
        )
    if not source_columns or not target_columns:
        return _degraded("Source or target has no columns to identify candidate keys from.")

    user_payload: dict[str, Any] = {
        "source_columns": list(source_columns),
        "target_columns": list(target_columns),
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
        logger.warning("Candidate-key identification failed; degrading. %s", exc)
        return _degraded(f"AI candidate-key identification failed: {exc}")

    if not isinstance(payload, dict):
        return _degraded("AI returned an unexpected response for candidate-key identification.")

    outcome = get_last_llm_outcome()
    return {
        "source": _gate_side(payload.get("source"), source_columns),
        "target": _gate_side(payload.get("target"), target_columns),
        "degraded": False,
        "degraded_reason": None,
        "provider": (outcome.provider_used if outcome and outcome.provider_used else None),
    }
