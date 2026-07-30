"""Live-schema field verification + business-role detection for Auto mode.

Two distinct, deliberately narrow mechanisms — neither one ever assumes a
literal field name:

* :func:`match_proposed_to_schema` — a direct Python port of
  ``frontend/src/reconciliation/lib/fieldMatching.js``. Validates the
  mapping-sheet's LLM-extracted candidate field names against a connector's
  REAL live schema (case/punctuation-insensitive, with the same TABLE-FIELD
  trailing-segment fallback, e.g. ``VBAP-MATNR`` -> ``MATNR``). It deliberately
  does NOT do semantic mapping (``MATNR`` -> ``Material``) — unmatched
  proposals are reported, never guessed. Kept in lockstep with the frontend
  original; port any future change there here too.

* :func:`detect_roles_for_columns` — a Python port of
  ``frontend/src/reconciliation/lib/fieldRoleAliases.js``'s alias-based
  business-role detection (Product/Location/Date/Quantity), applied to
  whatever columns a live fetch actually returned. This is the ONE legitimate
  reuse of "known aliases" in this module: it recognizes a role from a
  column's real, already-fetched name — it never supplies a name to fetch.
"""

from __future__ import annotations

import re

# ── schema verification (port of fieldMatching.js) ──────────────────────────


def _normalize(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _candidate_keys(proposed: str) -> set[str]:
    keys: set[str] = set()
    whole = _normalize(proposed)
    if whole:
        keys.add(whole)
    segment = re.split(r"[-/.]", str(proposed or ""))[-1]
    seg_key = _normalize(segment)
    if seg_key:
        keys.add(seg_key)
    return keys


def match_proposed_to_schema(
    proposed_fields: list[str], schema_names: list[str]
) -> tuple[list[str], list[str]]:
    """Returns ``(matched, unmatched)`` — real schema names (original casing)
    the proposals resolve to, and proposals with no live-schema match."""
    index: dict[str, str] = {}
    for name in schema_names or []:
        key = _normalize(name)
        if key and key not in index:
            index[key] = name

    matched: list[str] = []
    matched_set: set[str] = set()
    unmatched: list[str] = []
    for proposed in proposed_fields or []:
        hit = None
        for key in _candidate_keys(proposed):
            if key in index:
                hit = index[key]
                break
        if hit:
            if hit not in matched_set:
                matched_set.add(hit)
                matched.append(hit)
        elif proposed:
            unmatched.append(proposed)
    return matched, unmatched


# ── business-role detection (port of fieldRoleAliases.js) ───────────────────

ROLE_ALIASES: dict[str, list[str]] = {
    "product": [
        "material", "materialcode", "materialnumber", "materialid",
        "materialdescription", "sku", "itemcode", "itemid", "itemnumber",
        "productid", "prdid", "productcode", "product",
    ],
    "location": [
        "plant", "plantcode", "plantid", "productionplant",
        "location", "locationcode", "locationid", "locid",
        "site", "sitecode", "facility",
    ],
    "date": [
        "date", "period", "periodid", "periodid0tstamp",
        "requesteddeliverydate", "deliverydate", "transactiondate", "orderdate",
    ],
    "quantity": [
        "quantity", "qty", "requestedquantity", "salesorderrequest",
        "salesqty", "orderqty",
    ],
}


def detect_roles_for_columns(columns: list[str]) -> dict[str, str]:
    """Maps ``role -> column name`` for whichever of ``columns`` matches a
    known alias for that role (first match wins, one column per role).
    Detects a role from a column that's already real (fetched/verified) —
    never a source of a field name to fetch."""
    result: dict[str, str] = {}
    for col in columns:
        key = _normalize(col)
        for role, aliases in ROLE_ALIASES.items():
            if role in result:
                continue
            if key in aliases:
                result[role] = col
    return result
