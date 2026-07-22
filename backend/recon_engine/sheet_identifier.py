"""Sheet-driven system identification + field pre-selection (LLM, allow-listed).

Given a parsed mapping sheet, infer:

* which SOURCE system it describes (from the naming convention of its source
  fields, e.g. ``VBAP-MATNR`` → S/4), and
* which TARGET system it describes (often stated directly, e.g. a "Target: IBP"
  banner), and
* the fields on each side the sheet says to compare/map.

Two hard rules make this safe:

1. **Allow-list discipline.** The connector the LLM may pick is constrained to
   the *configured & enabled* connectors from ``API_conn.connectors.registry``.
   Anything else the model thinks it sees is returned as evidence-bearing
   ``unidentified`` — never coerced to the nearest configured connector. A wrong
   system fetches entirely wrong data with no downstream check to catch it.
2. **Same provider chain as everything else.** The call goes through
   ``build_llm_client()`` (Groq primary → OpenAI fallback), not a bespoke Groq
   client. Any provider failure degrades to an empty/unidentified result rather
   than raising, so the wizard never dies because the LLM is unavailable — the
   human just falls back to manual connector selection.

Field *validation* against the live schema is intentionally NOT done here: the
LLM only proposes field names from the sheet; the deterministic intersection
with the real connector schema happens on the frontend once a side's connector
has actually loaded its schema.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from backend.API_conn.connectors import registry
from backend.recon_engine.config import get_settings
from backend.recon_engine.llm import build_llm_client, get_last_llm_outcome

logger = logging.getLogger("recon.sheet_identifier")

_CONFIDENCE_VALUES = ("high", "medium", "low")

# A technical TABLE-FIELD reference (VBAP-MATNR, VBEP-EDATU, VBAP-WERKS…). These
# identify the SOURCE *system*; per the asymmetric extraction rule they must
# NEVER be surfaced as candidate source fields. This regex is the deterministic
# safety net enforcing that even if the model leaks one into the source list.
_TABLE_FIELD_RE = re.compile(r"^[A-Z][A-Z0-9]*-[A-Z0-9_]+$")

_SYSTEM_PREAMBLE = """You identify which SAP systems a data-mapping sheet
describes AND which fields to compare on each side, so a reconciliation tool
can pre-select the right connectors and fields.

You receive a parsed mapping workbook (headers, rows, detected_columns,
mapping_candidates, and any preamble/banner rows above the header) and an
ALLOW-LIST of the configured connectors, each with a naming_convention hint.

Decide, independently for the SOURCE side and the TARGET side:
1. Which allowed connector (if any) the sheet describes, identified by its
   `kind`. Base the SOURCE decision on the naming convention of the source
   fields (TABLE-FIELD forms like VBAP-MATNR / VBEP-EDATU indicate S/4 OData).
   Base the TARGET decision on explicit banners/headers (e.g. "Target: IBP")
   and target-field naming.
2. The candidate fields to compare on that side, following the ASYMMETRIC
   field-extraction precedence below. The precedence is NOT the same for both
   sides — do NOT apply one consistent rule to both.

FIELD-EXTRACTION PRECEDENCE — ASYMMETRIC, read carefully:
* Technical TABLE-FIELD references (VBAP-MATNR, VBAP-WERKS, VBEP-EDATU, …) are
  used ONLY to recognize the SOURCE system. They must NEVER appear as candidate
  field labels on any side.
* SOURCE side (S/4): candidate fields are the BUSINESS DESCRIPTIONS — e.g.
  Material, Production Plant, Requested Quantity, Requested Delivery Date — NOT
  the technical references. If a row carries both VBAP-MATNR and "Material",
  emit "Material".
* TARGET side (IBP): candidate fields are the TECHNICAL field names — e.g.
  PRDID, LOCID, SALESORDERREQUEST, PERIODID0_TSTAMP — NOT business labels. If a
  row carries both PRDID and "Product ID", emit "PRDID".
* If only one name is present on a side, use it. If both are present, apply the
  side's rule above (source→business, target→technical) consistently.

OUTPUT RULES — follow all of them:
1. Respond with a single JSON object only, no prose/markdown/code fences:
   {"source": {...}, "target": {...}}
2. Each of "source" and "target" is:
   {"kind": "<one of the allowed kinds, or null>",
    "evidence": "<brief, concrete reason citing what you saw>",
    "confidence": "high" | "medium" | "low",
    "fields": ["<candidate field names per the precedence above>", ...]}
3. `kind` MUST be exactly one of the allowed connector kinds provided, OR null.
   If the sheet clearly describes a system that is NOT in the allow-list
   (e.g. BW InfoObjects/ADSO naming when no BW connector is allowed), set
   `kind` to null and NAME the system you suspect in `evidence`. NEVER pick the
   nearest allowed connector as a substitute — a wrong pick is worse than none.
4. `evidence` is always required, even when kind is null — it is shown to a
   human who must confirm. Keep it to one concrete sentence.
5. If you genuinely cannot tell, use kind=null, confidence="low", and say so.
"""


def _empty_side() -> dict[str, Any]:
    return {"kind": None, "evidence": "", "confidence": "low", "fields": []}


def _degraded_result(reason: str) -> dict[str, Any]:
    """A safe result the frontend treats as 'no auto-selection — go manual'."""
    return {
        "source": _side_result(_empty_side(), registry.SOURCE, warnings=[]),
        "target": _side_result(_empty_side(), registry.TARGET, warnings=[]),
        "warnings": [reason],
        "degraded": True,
        "degraded_reason": reason,
        "provider": None,
    }


def _clean_fields(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _side_result(
    raw: dict[str, Any], role: str, *, warnings: list[str]
) -> dict[str, Any]:
    """Normalize + allow-list one side of the LLM output.

    ``kind`` survives only if it is a configured connector for this role.
    A registered-but-unconfigured kind, or a completely unknown one, is
    demoted to unidentified with a warning — the raw suggestion is preserved
    for transparency but is never auto-selected.
    """
    suggested = raw.get("kind")
    suggested_kind = str(suggested).strip().lower() if suggested else None
    evidence = str(raw.get("evidence") or "").strip()
    confidence = str(raw.get("confidence") or "low").strip().lower()
    if confidence not in _CONFIDENCE_VALUES:
        confidence = "low"
    fields = _clean_fields(raw.get("fields"))

    # Asymmetric field-extraction guard: on the SOURCE side, a technical
    # TABLE-FIELD reference (VBAP-MATNR) is only ever an identifier of the
    # system — never a candidate field. Strip any that leaked into the list so
    # the human sees business descriptions (Material, Production Plant, …), and
    # note it. The TARGET side keeps technical names verbatim — do NOT filter it.
    if role == registry.SOURCE and fields:
        kept = [f for f in fields if not _TABLE_FIELD_RE.match(f)]
        dropped = [f for f in fields if _TABLE_FIELD_RE.match(f)]
        if dropped:
            warnings.append(
                "Technical references "
                f"({', '.join(dropped)}) were used to identify the source system, "
                "not shown as candidate fields — the business descriptions are used instead."
            )
        fields = kept

    configured = {c["kind"]: c for c in registry.get_configured_connectors(role=role)}

    result: dict[str, Any] = {
        "role": role,
        "kind": None,
        "connector_id": None,
        "label": None,
        "evidence": evidence,
        "confidence": confidence,
        "fields": fields,
        "suggested_kind": suggested_kind,
        "in_registry": registry.is_registered_kind(suggested_kind),
        "configured": False,
    }

    if suggested_kind and suggested_kind in configured:
        spec = configured[suggested_kind]
        result.update(
            {
                "kind": spec["kind"],
                "connector_id": spec["connector_id"],
                "label": spec["label"],
                "configured": True,
            }
        )
        return result

    # Not auto-selectable — explain why, without coercing.
    if suggested_kind and registry.is_registered_kind(suggested_kind):
        warnings.append(
            f"Sheet looks like '{suggested_kind}' for the {role} side, but that "
            f"connector is not configured/enabled — select the {role} connector manually."
        )
    elif suggested_kind:
        warnings.append(
            f"Sheet appears to describe '{suggested_kind}' for the {role} side, "
            f"which is not a registered connector — not auto-selected. "
            f"Evidence: {evidence or 'n/a'}"
        )
    else:
        warnings.append(
            f"Could not identify the {role} system from the sheet — "
            f"select the {role} connector manually."
        )
    return result


def identify_systems(
    parsed_sheet: dict[str, Any] | list[dict[str, Any]],
) -> dict[str, Any]:
    """Identify source/target connectors + candidate fields from a parsed sheet.

    Never raises on LLM failure: returns a ``degraded`` result the frontend
    treats as "no auto-selection, fall back to manual".
    """
    if not get_settings().any_llm_configured:
        return _degraded_result(
            "No AI provider is configured (GROQ_API_KEY / OPENAI_API_KEY) — "
            "identify the connectors manually."
        )

    allowed = registry.get_configured_connectors()
    if not allowed:
        return _degraded_result(
            "No connectors are configured/enabled in sap_config.yaml — "
            "nothing to auto-select."
        )

    allow_list = [
        {
            "kind": c["kind"],
            "role": c["role"],
            "label": c["label"],
            "naming_convention": c["table_prefix_hint"],
        }
        for c in allowed
    ]
    user_payload = {
        "allowed_connectors": allow_list,
        "mapping_sheet": parsed_sheet,
    }

    try:
        client = build_llm_client()
        payload = client.complete_json(
            [
                {"role": "system", "content": _SYSTEM_PREAMBLE},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, default=str)},
            ]
        )
    except Exception as exc:  # noqa: BLE001 — degradation is the contract
        logger.warning("Sheet identification failed; degrading to manual. %s", exc)
        return _degraded_result(f"AI system identification failed: {exc}")

    if not isinstance(payload, dict):
        return _degraded_result("AI returned an unexpected response for system identification.")

    warnings: list[str] = []
    source = _side_result(
        payload.get("source") if isinstance(payload.get("source"), dict) else {},
        registry.SOURCE,
        warnings=warnings,
    )
    target = _side_result(
        payload.get("target") if isinstance(payload.get("target"), dict) else {},
        registry.TARGET,
        warnings=warnings,
    )

    outcome = get_last_llm_outcome()
    return {
        "source": source,
        "target": target,
        "warnings": warnings,
        "degraded": False,
        "degraded_reason": None,
        "provider": (outcome.provider_used if outcome and outcome.provider_used else None),
    }
