"""Sheet-driven system identification + field pre-selection (LLM, allow-listed).

Given a parsed mapping sheet, infer:

* which SOURCE system it describes (from the naming convention of its source
  fields, e.g. ``VBAP-MATNR`` → S/4), and
* which TARGET system it describes (often stated directly, e.g. a "Target: IBP"
  banner), and
* the fields on each side the sheet says to compare/map, and
* which ENTITIES to fetch on each side and how to JOIN them, when the sheet says
  so — additional output of this SAME call, not a second LLM flow. Entities are
  gated against the live entity list of the connector *that side resolved to*
  (see ``entity_catalog``), so a source-side result can only ever contain
  source-connector entities. The result pre-populates the Join Builder canvas;
  the human still confirms it there. Sheets that say nothing about entities are
  silent — no warnings, no empty-list noise.

Two hard rules make this safe:

1. **Allow-list discipline.** The connector the LLM may pick is constrained to
   the *configured & enabled* connectors from ``API_conn.connectors.registry``.
   Anything else the model thinks it sees is returned as evidence-bearing
   ``unidentified`` — never coerced to the nearest configured connector. A wrong
   system fetches entirely wrong data with no downstream check to catch it.
2. **Same provider as everything else.** The call goes through the
   Azure-AI-Foundry-only ``build_llm_client()`` (no fallback), not a bespoke client. A
   provider failure degrades to an empty/unidentified result rather than
   raising, so the wizard never dies because the LLM is unavailable — the
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
from backend.recon_engine.entity_join_parser import (
    entities_present_in_sheet,
    mentions_entity_join,
    names_from_payload,
    resolve_entity_from_fields,
    resolve_entity_join,
)
from backend.recon_engine.llm import build_llm_client, get_last_llm_outcome

logger = logging.getLogger("recon.sheet_identifier")

_CONFIDENCE_VALUES = ("high", "medium", "low")


def _norm_token(value: Any) -> str:
    """Case/punctuation-insensitive form, for comparing loose sheet tokens."""
    return re.sub(r"[^a-z0-9]", "", str(value).lower())

# A technical TABLE-FIELD reference (VBAP-MATNR, VBEP-EDATU, VBAP-WERKS…). These
# identify the SOURCE *system*; per the asymmetric extraction rule they must
# NEVER be surfaced as candidate source fields. This regex is the deterministic
# safety net enforcing that even if the model leaks one into the source list.
_TABLE_FIELD_RE = re.compile(r"^[A-Z][A-Z0-9]*-[A-Z0-9_]+$")

_SYSTEM_PREAMBLE = """You identify which SAP systems a data-mapping sheet
describes, which fields to compare on each side, AND which entities to fetch and
how to join them, so a reconciliation tool can pre-select the right connectors,
fields, entities and join.

You receive a parsed mapping workbook (headers, rows, detected_columns,
mapping_candidates, join_conditions, and any preamble/banner rows above the
header) and an ALLOW-LIST of the configured connectors, each with a
naming_convention hint and — when known — that connector's available_entities
(its live entity list).

This sheet's layout is inconsistent — business names, technical table.field
references, entity names, and dataset identifiers may appear in any column,
including one seemingly meant for something else (e.g. an entity name
appearing in a "Join Condition" cell). Reason from context: a technical
reference matching TABLE-FIELD notation (letters, dash/dot, more letters) is
evidence of which system/tables are involved, never a field name to fetch. A
bare business-sounding phrase near it is the actual field. A value that looks
like a CDS view or entity name (often prefixed A_/I_/similar) is an entity,
not a field. A short alphanumeric code with no other business description
nearby, especially under a target-system header, may be a target
dataset/planning-area identifier.

Extract only what this specific sheet's evidence supports. Never assume a
field, entity, or identifier because it looks familiar from another dataset —
every value you output must trace to something actually present in this
sheet, and must be verified against the live connector's real schema before
use (a downstream step will fetch using exactly what you output; if you
invent or guess, that fetch will fail loudly rather than silently).

Decide, independently for the SOURCE side and the TARGET side:
1. Which allowed connector (if any) the sheet describes, identified by its
   `kind`. Base the SOURCE decision on the naming convention of the source
   fields (TABLE-FIELD forms like VBAP-MATNR / VBEP-EDATU indicate S/4 OData).
   Base the TARGET decision on explicit banners/headers (e.g. "Target: IBP")
   and target-field naming.
2. The candidate fields to compare on that side, following the ASYMMETRIC
   field-extraction precedence below. The precedence is NOT the same for both
   sides — do NOT apply one consistent rule to both.
3. The ENTITIES to fetch on that side and any JOIN between them — see the
   ENTITY + JOIN section below. Only when the sheet actually says something;
   otherwise leave them empty/null.

ENTITY + JOIN EXTRACTION:
* Evidence is often LOOSELY PLACED — a table/entity name inside a "Source
  Table/Field" cell, a second entity named in a "Join Condition" cell, a join
  described in free-text notes. Look EVERYWHERE (headers, rows,
  detected_columns, mapping_candidates, join_conditions, preamble), not just a
  dedicated "entity" column.
* Ground every entity in that side's connector's available_entities and return
  its EXACT name from that list (e.g. a sheet saying "sales order item" → an
  available "A_SalesOrderItem"). If the sheet names something with NO
  corresponding available entity, return the sheet's name VERBATIM so it can be
  flagged downstream — NEVER substitute a different available entity for it, and
  NEVER invent one.
* Take a side's entities ONLY from that side's own connector. Never place a
  source connector's entity on the target side, or vice versa.
* Name EVERY entity the sheet references for that side, not just the first.
  A bare entity name sitting in a "Join Condition" cell is a SECOND entity to
  join to the primary — report both, in `entities`, primary first. Equally, a
  side with no join at all still needs its single entity named: do not leave
  `entities` empty just because there is nothing to join.
* PLANNING AREA (SAP IBP): report `planning_area` when the sheet states one —
  in a banner, a header, a notes cell, or a column value (ids look like "A07",
  "BTB2024", "ZASC", "ZOBP2508", "PO2Trans"). Use an id from that connector's
  known_planning_areas when one matches, and null when the sheet doesn't say.
  This matters more than it looks: every planning area exposes the SAME planning
  levels with the SAME field names, so without it the right entity cannot be
  told apart from the same entity in another area. Never guess an area.
  A planning-area id is NOT a field: report it in `planning_area` only, and keep
  it out of `fields`. It often sits alone in a cell of a target column with no
  row of its own, which is easy to mistake for a field name.
* Order matters: the FIRST entity is the primary.
* `join_type` only if the sheet EXPLICITLY states it; `keys` only if the join
  fields are explicitly stated. Otherwise null — a downstream default applies.
  Do not guess either one.

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
    "fields": ["<candidate field names per the precedence above>", ...],
    "planning_area": "<IBP planning area id the sheet states, or null>",
    "entities": ["<entity from THIS side's available_entities; first is primary>", ...],
    "join_type": "inner" | "left" | "right" | "full" | null,
    "keys": [{"left": "<field on the primary>", "right": "<field on the joined entity>"}] | null}
3. `kind` MUST be exactly one of the allowed connector kinds provided, OR null.
   If the sheet clearly describes a system that is NOT in the allow-list
   (e.g. BW InfoObjects/ADSO naming when no BW connector is allowed), set
   `kind` to null and NAME the system you suspect in `evidence`. NEVER pick the
   nearest allowed connector as a substitute — a wrong pick is worse than none.
4. `evidence` is always required, even when kind is null — it is shown to a
   human who must confirm. Keep it to one concrete sentence.
5. If you genuinely cannot tell, use kind=null, confidence="low", and say so.
6. `entities` is [] and `join_type`/`keys` are null when the sheet gives no
   entity/join evidence for that side. An empty result is correct and expected —
   the user then names the entities themselves. Do NOT fill them speculatively.
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


def _attach_entity_join(
    result: dict[str, Any],
    raw: dict[str, Any],
    entity_catalog: dict[str, dict[str, Any]] | None,
    warnings: list[str],
    parsed_sheet: Any = None,
) -> None:
    """Gate this side's entity/join evidence onto ``result``, in place.

    The gate is handed ONE connector's live entity list — the one this side
    actually resolved to — which is what makes cross-wiring structurally
    impossible: the target's entities are never in scope while resolving the
    source. A side whose connector wasn't identified (or whose live list wasn't
    loaded) can't be verified, so its named entities are flagged rather than
    trusted.

    When the sheet names NO entity but does list fields for this side, the
    entity is resolved from those fields against the connector's live property
    lists (``entity_source="fields"``). Without that fallback an IBP side never
    resolves at all: IBP sheets list technical field names and never an OData
    entity-set name, so there is nothing for the model to name.
    """
    kind = result["kind"]
    entry = (entity_catalog or {}).get(kind) if kind else None
    available = (entry or {}).get("entities")
    known_areas = (entry or {}).get("planning_areas") or []
    named = names_from_payload(raw)

    if not mentions_entity_join(raw) and not result["fields"]:
        return  # the sheet said nothing at all for this side — stay silent

    if available is None:
        # Nothing to validate against — flag, never auto-place.
        result["unresolved_entities"] = named
        if named:
            reason = (
                f"the {result['role']} connector wasn't identified from the sheet"
                if not kind
                else f"the live entity list for '{kind}' wasn't available"
            )
            warnings.append(
                f"The sheet names {', '.join(named)} on the {result['role']} side, but "
                f"{reason} — not pre-placed. Add the entities on the Join Builder canvas."
            )
        return

    resolved = resolve_entity_join(
        raw, available, kind, warnings=warnings, known_areas=known_areas
    )
    entity_source = "sheet" if resolved["entities"] else None
    ambiguous: list[str] = []

    # Deterministic net: any live entity name that literally appears in the
    # sheet belongs on this side, whether or not the model reported it. The
    # second entity of a join is typically parked bare in a "Join Condition"
    # cell, which the model does miss. Appended after the model's own list so
    # its ordering (first = primary) is preserved; each name is a verified live
    # entity, so this adds facts, never guesses.
    for name in entities_present_in_sheet(parsed_sheet, available):
        if name not in resolved["entities"]:
            resolved["entities"].append(name)
            entity_source = entity_source or "sheet"
    if resolved["entities"] and not resolved["primary"]:
        resolved["primary"] = resolved["entities"][0]

    # A planning-area id is not a field. Real sheets park it alone in a cell of
    # a target column ("ZOBP2508" with the rest of the row blank), which reads
    # exactly like a field name — so strip it deterministically rather than
    # trusting the model to have kept it out. Left in, it would be pre-selected
    # as a column and would dilute the field-based entity match below.
    if resolved["planning_area"]:
        area_norm = _norm_token(resolved["planning_area"])
        kept = [f for f in result["fields"] if _norm_token(f) != area_norm]
        if len(kept) != len(result["fields"]):
            result["fields"] = kept

    # Fallback: the sheet named NO entity at all, but it did name fields. Ask
    # the live metadata which entity actually holds them. Gated on `named` being
    # empty, not merely on nothing having resolved: when the sheet did name
    # something and it failed the existence gate, that name stays flagged and
    # nothing takes its place — substituting a different entity for one the user
    # actually wrote is precisely what this feature must never do.
    if not named and not resolved["entities"] and result["fields"]:
        hit = resolve_entity_from_fields(
            result["fields"],
            (entry or {}).get("properties"),
            scope=resolved["planning_area"],
        )
        if hit and hit.get("entity"):
            resolved["entities"] = [hit["entity"]]
            resolved["primary"] = hit["entity"]
            entity_source = "fields"
            area_note = (
                f" within planning area {resolved['planning_area']}"
                if resolved["planning_area"]
                else ""
            )
            result["entity_evidence"] = (
                f"Matched {hit['entity']}{area_note} from the {result['role']} fields the sheet "
                f"lists ({hit['matched']} of {len(result['fields'])} exist on it) — the sheet "
                f"names no entity directly."
            )
        elif hit and hit.get("ambiguous"):
            # The same planning level in several planning areas. Choosing one on
            # property count would be an arbitrary pick of WHICH PLANNING AREA to
            # read — wrong data with nothing downstream to catch it.
            ambiguous = hit["ambiguous"]
            warnings.append(
                f"The {result['role']} fields match {len(ambiguous)} entities equally well "
                f"({', '.join(ambiguous[:5])}{'…' if len(ambiguous) > 5 else ''}) — the sheet "
                f"doesn't say which planning area. Select the planning area, or pick the entity "
                f"on the Join Builder canvas."
            )

    result.update(
        {
            "entities": resolved["entities"],
            "primary_entity": resolved["primary"],
            "join_type": resolved["join_type"],
            "join_keys": resolved["keys"],
            "unresolved_entities": resolved["unresolved"],
            "entity_source": entity_source,
            "planning_area": resolved["planning_area"],
            "ambiguous_entities": ambiguous,
        }
    )


def _side_result(
    raw: dict[str, Any],
    role: str,
    *,
    warnings: list[str],
    entity_catalog: dict[str, dict[str, Any]] | None = None,
    parsed_sheet: Any = None,
) -> dict[str, Any]:
    """Normalize + allow-list one side of the LLM output.

    ``kind`` survives only if it is a configured connector for this role.
    A registered-but-unconfigured kind, or a completely unknown one, is
    demoted to unidentified with a warning — the raw suggestion is preserved
    for transparency but is never auto-selected.

    ``entity_catalog`` maps a connector kind to its live entity list; it gates
    this side's entity/join output (see :func:`_attach_entity_join`). Omitting it
    simply leaves the entity/join fields empty — identification itself is
    unaffected.
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
        # Entity/join pre-population for the Join Builder canvas. Empty means
        # "the sheet didn't say" — the canvas then behaves exactly as before.
        # `join_type`/`join_keys` stay None unless the sheet stated them, so the
        # canvas applies its own single default policy.
        "entities": [],
        "primary_entity": None,
        "join_type": None,
        "join_keys": None,
        "unresolved_entities": [],
        # How the entity was determined: "sheet" (named outright), "fields"
        # (matched from the fields the sheet lists, against live metadata), or
        # None (nothing determined). Surfaced in the Step-1 details.
        "entity_source": None,
        "entity_evidence": "",
        # The IBP planning area this side is scoped to, and the entities that
        # tied when no area was established. Both drive the Step-1 selector.
        "planning_area": None,
        "ambiguous_entities": [],
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
        _attach_entity_join(result, raw, entity_catalog, warnings, parsed_sheet)
        return result

    # Entities can't be verified without a resolved connector — flag them.
    _attach_entity_join(result, raw, entity_catalog, warnings, parsed_sheet)

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
    entity_catalog: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Identify source/target connectors, candidate fields, entities + join.

    ``entity_catalog`` maps a connector kind (``"s4"``, ``"ibp"``) to
    ``{"entities": [names], "properties": {entity: [property names]}}``.
    Supplying it does three things in this ONE call: the names ground the model
    (so a sheet's loose "sales order item" resolves to the connector's exact
    entity name); the names gate the result — each side's entities are validated
    against the list of the connector *that side* resolved to, and nothing else;
    and the properties back the deterministic fallback for a side that lists
    fields but names no entity. Omit it and identification behaves exactly as
    before, with empty entity/join fields.

    Never raises on LLM failure: returns a ``degraded`` result the frontend
    treats as "no auto-selection, fall back to manual".
    """
    if not get_settings().any_llm_configured:
        return _degraded_result(
            "No AI provider is configured (AZURE_FOUNDRY_MODEL) — "
            "identify the connectors manually."
        )

    allowed = registry.get_configured_connectors()
    if not allowed:
        return _degraded_result(
            "No connectors are configured/enabled in sap_config.yaml — "
            "nothing to auto-select."
        )

    # Each allowed connector carries its own live entity list, so the model sees
    # which entities are legal for which side and can ground a loose sheet name
    # in an exact one. A connector whose list couldn't be loaded simply omits it.
    allow_list = []
    for c in allowed:
        entry = {
            "kind": c["kind"],
            "role": c["role"],
            "label": c["label"],
            "naming_convention": c["table_prefix_hint"],
        }
        # Only the NAMES are sent to the model; the property index stays
        # server-side (it backs the deterministic field-based fallback) so it
        # adds no token cost.
        available = (entity_catalog or {}).get(c["kind"], {}).get("entities")
        if available:
            entry["available_entities"] = available
        allow_list.append(entry)
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

    # Each side is resolved independently against its own connector's entity
    # list — the source call never sees the target's entities, and vice versa.
    warnings: list[str] = []
    source = _side_result(
        payload.get("source") if isinstance(payload.get("source"), dict) else {},
        registry.SOURCE,
        warnings=warnings,
        entity_catalog=entity_catalog,
        parsed_sheet=parsed_sheet,
    )
    target = _side_result(
        payload.get("target") if isinstance(payload.get("target"), dict) else {},
        registry.TARGET,
        warnings=warnings,
        entity_catalog=entity_catalog,
        parsed_sheet=parsed_sheet,
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
