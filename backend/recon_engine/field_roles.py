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

import datetime
import re
from typing import Any

import pandas as pd

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


def _is_plain_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    text = str(value).strip().replace(",", "")
    if not text:
        return False
    try:
        float(text)
        return True
    except ValueError:
        return False


def _is_parseable_date(value: Any) -> bool:
    if isinstance(value, (pd.Timestamp, datetime.date, datetime.datetime)):
        return True
    text = str(value).strip()
    if not text:
        return False
    try:
        pd.to_datetime(text, errors="raise")
        return True
    except (ValueError, TypeError):
        return False


def detect_roles_from_sample(
    columns: list[str],
    sample_rows: list[dict[str, Any]],
    exclude: set[str],
) -> dict[str, str]:
    """Content-based fallback for the ``date``/``quantity`` business-key
    roles, used only when :func:`detect_roles_for_columns`'s name-alias match
    couldn't find them on a side. Never fetches anything extra — operates on
    the handful of rows (top 3) already pulled for schema preview.

    A column is assigned ``quantity`` when EVERY sampled non-empty value is a
    plain number, and ``date`` when EVERY sampled non-empty value parses as a
    date and is NOT a plain number (numeric-first ordering keeps a quantity
    column like zero-padded amounts from being misread as a date). Never
    considers a column already claimed by another role (``exclude``) or
    empty of sample values.
    """
    result: dict[str, str] = {}
    candidates = [c for c in columns if c not in exclude]

    def _values(col: str) -> list[Any]:
        return [row[col] for row in sample_rows if row.get(col) not in (None, "")]

    for col in candidates:
        values = _values(col)
        if values and all(_is_plain_number(v) for v in values):
            result["quantity"] = col
            break

    for col in candidates:
        if col == result.get("quantity"):
            continue
        values = _values(col)
        if values and all(_is_parseable_date(v) and not _is_plain_number(v) for v in values):
            result["date"] = col
            break

    return result
