"""Entity + join identification → pre-populates the Join Builder canvas.

Two paths reach the same place, and they share ONE validator:

* **Sheet path (primary).** Entities/join come out of the mapping-sheet
  identification call that already exists — :func:`sheet_identifier.identify_systems`
  emits them as additional fields on each side. There is deliberately no second
  sheet-reading LLM flow in this module; that module calls
  :func:`resolve_entity_join` below for its gating.
* **Free-text fallback.** :func:`parse_entity_join` turns a typed instruction
  ("join salesorder and scheduleline with left join on salesorder key") into the
  same structure, through the same Azure-AI-Foundry-only ``build_llm_client()`` (no
  fallback) every other LLM call in the codebase uses.

Three rules make this safe, mirroring ``sheet_identifier``/``field_mapper``:

1. **Existence gate.** Every entity the model returns must resolve to a real
   entity in the connector's live list (exact, then case/punctuation-insensitive).
   Anything else is FLAGGED (``unresolved`` + a warning) — never swapped for a
   real entity, never invented.
2. **One resolution per side.** The gate is handed exactly one connector's entity
   list, so a source-side result can only ever contain source-connector entities.
   Cross-wiring is structurally impossible rather than merely avoided.
3. **One default policy.** ``join_type`` is constrained to the allow-list; a type
   or keys the user did not state are left ``None`` so the *canvas* applies its
   existing default (``addJoin``: ``type="left"``, keys mirrored from the
   relationship's ``suggested_keys``). This module never invents a default and
   never executes a join — its output only pre-places nodes on the canvas, which
   stays human-editable.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from backend.recon_engine.config import get_settings
from backend.recon_engine.llm import build_llm_client, get_last_llm_outcome

logger = logging.getLogger("recon.entity_join")

# Allow-listed join types (matches the Join Builder's constrained set).
JOIN_TYPES = ("inner", "left", "right", "full")


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def entity_names(entities: Any) -> list[str]:
    """Flatten a live entity list (``[{name, entity_type}]`` or ``[str]``) to names."""
    names: list[str] = []
    for e in entities or []:
        name = str(e.get("name") if isinstance(e, dict) else e or "").strip()
        if name:
            names.append(name)
    return names


def _clean_keys(value: Any) -> list[dict[str, str]] | None:
    if not isinstance(value, list):
        return None
    out: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        left = str(item.get("left") or "").strip()
        right = str(item.get("right") or "").strip()
        if not left and not right:
            continue
        out.append({"left": left or right, "right": right or left})
    return out or None


def empty_entity_join() -> dict[str, Any]:
    """The neutral spec: nothing pre-placed, canvas defaults apply untouched."""
    return {
        "primary": None,
        "entities": [],
        "join_type": None,
        "keys": None,
        "unresolved": [],
        # The IBP planning area scoping this side, when one was identified or
        # chosen. None means "not established" — which is a blocker for
        # field-based resolution, never something to guess past.
        "planning_area": None,
        "ambiguous": [],
    }


def names_from_payload(raw: Any) -> list[str]:
    """The entity names a model payload claims, trimmed — before any gating."""
    if not isinstance(raw, dict):
        return []
    return [str(x).strip() for x in (raw.get("entities") or []) if str(x).strip()]


def in_scope(entity: str, scope: str | None) -> bool:
    """Whether an entity belongs to ``scope`` (e.g. an IBP planning area).

    Deliberately a case/punctuation-insensitive CONTAINS test rather than a
    prefix or separator rule: IBP services differ in how they qualify entity-set
    names with the planning area, and assuming a layout would silently exclude
    the right entity on a service that names things differently.
    """
    if not scope:
        return True
    return _norm(scope) in _norm(entity)


def discover_scopes(entity_names_list: Any, *, min_members: int = 2) -> list[str]:
    """Planning-area-like groupings discovered from live entity-set names.

    IBP qualifies its entity sets by planning area (A07, BTB2024, ZASC,
    ZOBP2508, PO2Trans, …), so the same planning level appears once per area.
    We infer the areas from the names themselves — the leading segment before
    the first separator, kept only when several entities share it — rather than
    hardcoding any list. Used to offer a manual choice when nothing identifies
    the area; it never auto-selects one.
    """
    counts: dict[str, int] = {}
    for name in entity_names_list or []:
        text = str(name).strip()
        head = re.split(r"[_\-/.]", text, maxsplit=1)[0].strip()
        # A leading segment equal to the whole name tells us nothing about
        # grouping, and a 1-2 char fragment is noise rather than an area id.
        if head and head != text and len(head) >= 2:
            counts[head] = counts.get(head, 0) + 1
    return sorted(h for h, n in counts.items() if n >= min_members)


def resolve_entity_from_fields(
    fields: Any,
    properties_by_entity: dict[str, list[str]] | None,
    *,
    scope: str | None = None,
    min_matches: int = 2,
    min_coverage: float = 0.5,
) -> dict[str, Any] | None:
    """Pick the live entity whose OWN properties cover the fields a sheet lists.

    The fallback for a side that names no entity at all — the normal case for
    IBP, whose mapping sheets list technical FIELD names (PRDID, LOCID,
    SALESORDERREQUEST) but never an OData entity-set name. S/4 sheets name
    tables, so the model can name an entity there; IBP gives it nothing to name.

    Deterministic and non-inventing: the winner must be in the live list AND
    must really contain the sheet's fields, per the connector's own
    ``$metadata`` (already parsed and cached, so this costs no extra calls).

    ``scope`` narrows the candidates to one planning area. It matters enormously
    on IBP: every planning area exposes the same planning levels with the same
    field names, so WITHOUT a scope the sheet's fields match many entities
    equally well. Any tie on match count is therefore reported as ambiguous and
    never broken — picking the wrong planning area fetches entirely wrong data,
    which is precisely the outcome no downstream check would catch.

    Returns ``{entity, matched, coverage, considered}`` on a decisive match,
    ``{ambiguous: [names…]}`` when several fit equally, or ``None``.
    """
    names = [str(f).strip() for f in (fields or []) if str(f).strip()]
    if not names or not properties_by_entity:
        return None

    wanted = {_norm(n) for n in names}
    wanted.discard("")
    if not wanted:
        return None

    scored: list[tuple[int, str]] = []
    for entity, props in properties_by_entity.items():
        if not in_scope(entity, scope):
            continue
        prop_norms = {_norm(p) for p in props or []}
        matched = len(wanted & prop_norms)
        if matched:
            scored.append((matched, entity))
    if not scored:
        return None

    best_matched = max(m for m, _ in scored)
    if best_matched < min_matches or best_matched / len(wanted) < min_coverage:
        return None

    leaders = sorted(e for m, e in scored if m == best_matched)
    if len(leaders) > 1:
        # Several entities cover the fields equally well — typically the same
        # planning level across planning areas. A property-count tie-break here
        # would be an arbitrary choice dressed up as a decision, so report the
        # candidates and let the planning area (or the human) settle it.
        return {"ambiguous": leaders}

    return {
        "entity": leaders[0],
        "matched": best_matched,
        "coverage": round(best_matched / len(wanted), 2),
        "considered": len(scored),
    }


# A live entity name found as a fragment of longer text needs to be long enough
# that the match means something; a short name could appear inside unrelated
# prose by coincidence. Whole-cell matches bypass this.
_MIN_SUBSTRING_ENTITY_LEN = 4


def _walk_strings(value: Any) -> list[str]:
    """Every string in a parsed sheet, in document order."""
    out: list[str] = []
    if isinstance(value, str):
        if value.strip():
            out.append(value)
    elif isinstance(value, dict):
        for item in value.values():
            out.extend(_walk_strings(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            out.extend(_walk_strings(item))
    return out


def entities_present_in_sheet(parsed_sheet: Any, available: list[str] | None) -> list[str]:
    """Live entity names that literally appear somewhere in the parsed sheet.

    The deterministic net behind the model's entity extraction. A sheet cell
    holding ``A_SalesOrderScheduleLine`` and a connector whose live list holds
    ``A_SalesOrderScheduleLine`` is an exact, verifiable correspondence — not an
    inference — so it should not depend on the model having noticed the cell.
    Real sheets bury the second entity of a join in a "Join Condition" cell with
    the rest of the row blank, which is easy to miss.

    Scanning every cell is side-safe by construction: names are matched against
    ONE connector's live list, so an S/4 entity can never surface from a scan
    scoped to IBP, or vice versa — the same property that makes the gate safe.

    Returns the names in order of first appearance.
    """
    if not available:
        return []

    lookup = {_norm(name): name for name in available if _norm(name)}
    found: list[str] = []
    seen: set[str] = set()

    for text in _walk_strings(parsed_sheet):
        cell = _norm(text)
        if not cell:
            continue
        hits = [
            norm
            for norm in lookup
            if norm == cell
            or (len(norm) >= _MIN_SUBSTRING_ENTITY_LEN and norm in cell)
        ]
        # "A_SalesOrder" is a substring of "A_SalesOrderItem": when a cell
        # matches both, only the most specific name is really named there.
        specific = [n for n in hits if not any(n != o and n in o for o in hits)]
        for norm in sorted(specific, key=len, reverse=True):
            name = lookup[norm]
            if name not in seen:
                seen.add(name)
                found.append(name)
    return found


def mentions_entity_join(raw: Any) -> bool:
    """True when a payload carries ANY entity/join intent worth gating.

    Lets callers stay silent (no warnings, no empty-list noise) for sheets that
    simply say nothing about entities — the common case.
    """
    if not isinstance(raw, dict):
        return False
    return bool(
        names_from_payload(raw)
        or raw.get("join_type") not in (None, "", "null", "none")
        or raw.get("keys")
    )


def resolve_planning_area(
    stated: Any,
    available: list[str] | None,
    known: list[str] | None,
    warnings: list[str],
) -> str | None:
    """Validate a stated planning area against the LIVE ENTITY NAMES.

    Validation deliberately asks "does any real entity belong to this area?"
    rather than "is this in the discovered area list". ``discover_scopes`` is a
    heuristic for populating a picker; an area it happens to miss (one exposing
    a single planning level, say) is still perfectly real, and rejecting a
    correctly-stated area would drop the one piece of information that makes
    IBP entity resolution unambiguous.

    An area no entity belongs to is dropped with a warning — filtering by it
    would match nothing and quietly look like "couldn't identify".
    """
    area = str(stated or "").strip()
    if not area:
        return None
    if not available:
        return area
    for entity in available:
        if in_scope(entity, area):
            # Prefer the discovered spelling so the UI shows a consistent id.
            for candidate in known or []:
                if _norm(candidate) == _norm(area):
                    return candidate
            return area
    hint = f" (discovered: {', '.join(known[:8])})" if known else ""
    warnings.append(
        f"Planning area '{area}' doesn't match any entity on this connector{hint} — ignored. "
        f"Select the planning area to narrow the entities."
    )
    return None


def resolve_entity_join(
    raw: Any,
    available: list[str],
    kind: str,
    *,
    warnings: list[str],
    known_areas: list[str] | None = None,
    planning_area: str | None = None,
) -> dict[str, Any]:
    """Gate a raw ``{entities, join_type, keys}`` payload against ONE live list.

    This is the single validator for both the sheet path and the free-text path.
    ``available`` is the live-discovered entity list of the connector named by
    ``kind`` — and only that connector, which is what keeps one side's entities
    out of the other side's result.

    Unknown entity names land in ``unresolved`` with a warning; an out-of-
    allow-list join type is dropped with a warning; anything the caller did not
    state stays ``None`` so the canvas default applies.
    """
    result = empty_entity_join()
    named = names_from_payload(raw)
    # An explicitly chosen area (the manual Step-1 selection) outranks whatever
    # the model read, since the human made that choice deliberately.
    stated_area = planning_area or (raw.get("planning_area") if isinstance(raw, dict) else None)
    area = resolve_planning_area(stated_area, available, known_areas, warnings)
    result["planning_area"] = area

    if not available:
        if named:
            result["unresolved"] = named
            warnings.append(
                f"No live entity list was available for the {kind.upper()} connector, so "
                f"{', '.join(named)} could not be verified — place the entities on the canvas."
            )
        return result

    # Existence gate: exact match first, then case/punctuation-insensitive.
    exact = set(available)
    lookup = {_norm(n): n for n in available}
    resolved: list[str] = []
    unresolved: list[str] = []
    seen: set[str] = set()
    for name in named:
        canonical = name if name in exact else lookup.get(_norm(name))
        if canonical:
            if canonical not in seen:
                seen.add(canonical)
                resolved.append(canonical)
        else:
            unresolved.append(name)
            warnings.append(
                f"'{name}' is not an entity in the {kind.upper()} connector — "
                f"flagged, not guessed. Pick an available entity on the canvas."
            )

    # Join type constrained to the allow-list; otherwise None (→ canvas default).
    join_type: str | None = None
    jt_raw = raw.get("join_type") if isinstance(raw, dict) else None
    if jt_raw is not None:
        jt = str(jt_raw).strip().lower()
        if jt in JOIN_TYPES:
            join_type = jt
        elif jt and jt not in ("null", "none"):
            warnings.append(
                f"Join type '{jt_raw}' is not one of {', '.join(JOIN_TYPES)} — "
                f"using the canvas default."
            )

    keys = _clean_keys(raw.get("keys") if isinstance(raw, dict) else None)

    # IBP is single-entity on this screen — keep the primary, drop join details.
    if kind == "ibp" and len(resolved) > 1:
        warnings.append(
            "IBP does not support joins on this screen — only the first entity "
            f"('{resolved[0]}') is used."
        )
        resolved = resolved[:1]
        join_type = None
        keys = None

    result.update(
        {
            "primary": resolved[0] if resolved else None,
            "entities": resolved,
            "join_type": join_type,
            "keys": keys,
            "unresolved": unresolved,
        }
    )
    return result


# ── free-text fallback (instruction → validated {entities, join_type, keys}) ──

_PARSE_PREAMBLE = """You convert a plain-language ENTITY + JOIN instruction into a
structured spec that pre-populates a Join Builder canvas.

You are given the connector's AVAILABLE ENTITIES (its live list), any KNOWN
PLANNING AREAS, and the user's instruction. Extract:
- "planning_area": the SAP IBP planning area the user names (e.g. "A07",
  "ZOBP2508", "PO2Trans"), if they name one, else null. Every planning area
  exposes the same planning levels, so this is what tells entities apart. Use a
  value from the known list when one matches; never invent an area.
- "entities": the entities named, IN ORDER — the FIRST is the primary. Choose ONLY
  from the available list; map a loose name to the closest available entity by name
  (e.g. "sales order item" → an available "A_SalesOrderItem"). If the instruction
  names something that has NO corresponding available entity, still return that name
  VERBATIM so it can be flagged downstream — NEVER substitute a different available
  entity for it.
- "join_type": one of "inner", "left", "right", "full" if the instruction EXPLICITLY
  states it, otherwise null. Do not guess.
- "keys": the join key field pairs IF explicitly stated, as
  [{"left": "<field on the primary>", "right": "<field on the joined entity>"}],
  otherwise null. If a single key name is given for both sides, use it for both.

OUTPUT — a single JSON object only, no prose/markdown/code fences:
{"planning_area": "<area>" | null,
 "entities": ["<entity>", ...],
 "join_type": "inner"|"left"|"right"|"full"|null,
 "keys": [{"left": "...", "right": "..."}] | null}

Rules:
- NEVER invent an entity the instruction does not imply.
- Do NOT guess a join_type or keys the user did not state — leave them null so the
  canvas applies its own default.
- This is generic: work from whatever entities and join intent the text names.
"""


def _empty_parse() -> dict[str, Any]:
    return {
        **empty_entity_join(),
        "warnings": [],
        "degraded": False,
        "degraded_reason": None,
        "provider": None,
    }


def _degraded_parse(reason: str) -> dict[str, Any]:
    result = _empty_parse()
    result.update({"warnings": [reason], "degraded": True, "degraded_reason": reason})
    return result


def parse_entity_join(
    text: Any, entities: Any, kind: str, planning_area: str | None = None
) -> dict[str, Any]:
    """Parse a free-text entity/join instruction into a validated, canvas-ready spec.

    The fallback for when the mapping sheet doesn't state entities/join — and a
    deliberate override when the user types one anyway. Goes through the same
    provider chain as every other LLM call, and through the same
    :func:`resolve_entity_join` gate as the sheet path, so a typed instruction is
    held to exactly the same existence rules. Never raises: any LLM/config
    problem returns a ``degraded`` result and the user builds the dataset by hand.
    """
    text = str(text or "").strip()
    if not text:
        return _empty_parse()

    available = entity_names(entities)
    if not get_settings().any_llm_configured:
        return _degraded_parse(
            "No AI provider is configured (AZURE_FOUNDRY_MODEL) — "
            "build the dataset manually."
        )
    if not available:
        return _degraded_parse("No live entities available for this connector.")

    known_areas = discover_scopes(available)
    user_payload = {
        "connector_kind": kind,
        "available_entities": available,
        "known_planning_areas": known_areas,
        "selected_planning_area": planning_area,
        "instruction": text,
    }
    try:
        client = build_llm_client()
        payload = client.complete_json(
            [
                {"role": "system", "content": _PARSE_PREAMBLE},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, default=str)},
            ]
        )
    except Exception as exc:  # noqa: BLE001 — degradation is the contract
        logger.warning("Entity/join parse failed; degrading. %s", exc)
        return _degraded_parse(f"AI entity/join parse failed: {exc}")

    if not isinstance(payload, dict):
        return _degraded_parse("AI returned an unexpected response for entity/join parse.")

    warnings: list[str] = []
    resolved = resolve_entity_join(
        payload,
        available,
        kind,
        warnings=warnings,
        known_areas=known_areas,
        planning_area=planning_area,
    )

    outcome = get_last_llm_outcome()
    return {
        **resolved,
        "warnings": warnings,
        "degraded": False,
        "degraded_reason": None,
        "provider": (outcome.provider_used if outcome and outcome.provider_used else None),
    }
