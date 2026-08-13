"""Interrupt-driven resolution for Auto-mode's RECOVERABLE Step-1 failures.

Three failure classes are recoverable via a single answer from the user —
entity not resolved, field/business-field not resolved, join key missing —
each handled here by pausing the graph with ``langgraph.types.interrupt()``
instead of raising. Genuinely unrecoverable failures (auth, network, no
configured connector, or a live schema with nothing in common to offer) never
reach this module — they still raise a plain exception and hard-stop via
``nodes.py``'s ``_run_step``, unchanged.

Every answer — a suggestion chip tapped or free text typed — is validated here
against the SAME live options the failing node already fetched (entity
catalog, schema property list), using the SAME existence check the node
itself uses, before it's accepted. An invalid answer loops back into another
``interrupt()`` call with freshly-ranked chips against the new attempt —
never accepted on faith, and never restarting the run.

LangGraph matches ``interrupt()`` calls to their resume values by call order
within one node execution, replaying earlier (already-answered) calls
transparently on each re-execution — so a ``while`` loop that calls
``interrupt()`` repeatedly is the correct, supported shape for "ask again
until valid", not a special case.
"""

from __future__ import annotations

import re
from typing import Any

from langgraph.types import interrupt

from backend.recon_engine.auto_pipeline.closeness import rank_closest
from backend.recon_engine.auto_pipeline.field_matching import match_proposed_to_schema


def _norm(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _ask(payload: dict[str, Any]) -> str:
    return str(interrupt(payload) or "").strip()


def resolve_entity_or_ask(*, side: str, kind: str, attempted: str, live_names: list[str]) -> str:
    """Resolve ``attempted`` to a real entity name in ``live_names``, or pause.

    Existence check mirrors ``IBPMetadataService.get_entity_properties`` /
    ``S4MetadataService._entity_type`` (exact, then case/punctuation-
    insensitive) — the same live list those raise "Unknown entity set" from,
    so a resolved name is guaranteed valid for the very next call against it.
    """
    if not live_names:
        raise RuntimeError(
            f"No live entities are available on the {kind.upper()} connector to resolve "
            f"{side} entity {attempted!r} against — nothing a single answer can fix."
        )

    exact = set(live_names)
    lookup = {_norm(n): n for n in live_names}
    candidate = attempted
    first = True
    while True:
        if candidate in exact:
            return candidate
        canonical = lookup.get(_norm(candidate))
        if canonical:
            return canonical
        chips = rank_closest(candidate, live_names, limit=4)
        message = (
            f'{side.capitalize()} entity "{candidate}" could not be resolved for {kind.upper()}.'
            if first
            else f'"{candidate}" is still not a valid {kind.upper()} entity.'
        )
        candidate = _ask(
            {
                "resolver": "entity",
                "side": side,
                "kind": kind,
                "attempted": candidate,
                "message": message,
                "options": chips,
                "all_options": live_names,
            }
        )
        first = False


def resolve_field_or_ask(
    *, side: str, kind: str, attempted_fields: list[str], live_fields: list[str]
) -> list[str]:
    """Resolve at least one live field name when NONE of ``attempted_fields``
    matched the connector's live schema (the ``match_proposed_to_schema`` gate
    ``nodes.py`` already runs before calling this). Returns a one-item
    matched-field list — the same shape ``match_proposed_to_schema`` returns
    on a successful match.
    """
    if not live_fields:
        raise RuntimeError(
            f"No live fields are available on the {kind.upper()} connector to resolve "
            f"{side} field(s) {attempted_fields!r} against — nothing a single answer can fix."
        )

    candidate = attempted_fields[0] if attempted_fields else ""
    first = True
    while True:
        matched, _ = match_proposed_to_schema([candidate], live_fields) if candidate else ([], [])
        if matched:
            return matched
        chips = rank_closest(candidate, live_fields, limit=4)
        message = (
            f"None of the mapping sheet's requested fields {attempted_fields!r} matched the "
            f"live {kind.upper()} schema."
            if first
            else f'"{candidate}" is still not a field on the live {kind.upper()} schema.'
        )
        candidate = _ask(
            {
                "resolver": "field",
                "side": side,
                "kind": kind,
                "attempted": candidate,
                "message": message,
                "options": chips,
                "all_options": live_fields,
            }
        )
        first = False


def resolve_join_key_or_ask(
    *,
    side: str,
    kind: str,
    primary_entity: str,
    joined_entity: str,
    primary_props: list[str],
    joined_props: list[str],
) -> list[dict[str, str]]:
    """Resolve a join key pair when neither the sheet nor the live schema's own
    relationship suggestion named a valid one.

    Candidates are property names shared by BOTH entities' live schemas —
    never invented — and the chosen name is used on both sides, mirroring the
    same-name default ``nodes.py`` already applies to a live-suggested key.
    """
    shared = [p for p in primary_props if _norm(p) in {_norm(x) for x in joined_props}]
    if not shared:
        raise RuntimeError(
            f'No properties are shared between "{primary_entity}" and "{joined_entity}" on the '
            f"live {kind.upper()} schema — no join key is possible between them."
        )

    lookup = {_norm(p): p for p in shared}
    candidate = ""
    first = True
    while True:
        canonical = lookup.get(_norm(candidate)) if candidate else None
        if canonical:
            return [{"left": canonical, "right": canonical}]
        chips = rank_closest(candidate, shared, limit=4) if candidate else shared[:4]
        message = (
            f'No valid join key between "{primary_entity}" and "{joined_entity}" — the mapping '
            "sheet named none the live schema could verify, and the live schema suggests none "
            "either."
            if first
            else f'"{candidate}" is not a property on both "{primary_entity}" and "{joined_entity}".'
        )
        candidate = _ask(
            {
                "resolver": "join_key",
                "side": side,
                "kind": kind,
                "attempted": candidate,
                "message": message,
                "options": chips,
                "all_options": shared,
            }
        )
        first = False
