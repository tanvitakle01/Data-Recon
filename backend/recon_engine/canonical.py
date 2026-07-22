"""Canonical, order-independent key for the attribute (field) mapping library.

THE dedup contract for :mod:`storage.attribute_mapping_store`: the same logical
set of columns must always produce the SAME key, no matter what order the
columns are supplied in or trivial case/whitespace differences. If lookup and
store-back ever computed the key differently, the same mapping would be stored
twice and never reused — silently defeating the whole feature. So there is
exactly ONE function here, imported by BOTH the lookup path (the infer route)
and the store-back path (run completion). Never inline this logic elsewhere.

Normalization rules (confirmed): per column name — strip surrounding
whitespace, case-fold; drop empties; de-duplicate; sort; join; SHA-256.
"""

from __future__ import annotations

import hashlib


def _normalize_columns(columns: list[str]) -> list[str]:
    """Trim + case-fold each name, drop blanks, de-duplicate, then sort.

    Sorting is what makes the key ORDER-INDEPENDENT — the identical column set
    supplied in a different order canonicalizes to the same list.
    """
    normalized = {
        folded
        for raw in (columns or [])
        if (folded := str(raw).strip().casefold())
    }
    return sorted(normalized)


def canonical_column_key(columns: list[str]) -> str:
    """SHA-256 over the normalized, sorted column names for one side.

    Source and target column lists are hashed separately (two keys), so a
    source set and a target set that happen to share column names still produce
    independent keys.
    """
    joined = "\n".join(_normalize_columns(columns))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()
