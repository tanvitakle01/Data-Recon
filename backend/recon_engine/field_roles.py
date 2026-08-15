"""Mode-agnostic, alias-based business-role detection.

A Python port of ``frontend/src/reconciliation/lib/fieldRoleAliases.js``'s
alias table, applied to columns that are already real (fetched/verified) —
this module never supplies a name to fetch, it only recognizes a role from
a column name that's already known to exist. Shared by both the Auto-mode
pipeline (``auto_pipeline/field_matching.py``, which re-exports these names
for backward compatibility) and the Manual-mode value-mapping route
(``routes/value_mapping.py``), so both modes agree on which pair is "the
date one" without either depending on the other's internals.
"""

from __future__ import annotations

import re

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


def _normalize(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


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
