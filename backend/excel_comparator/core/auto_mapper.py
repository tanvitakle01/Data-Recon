from __future__ import annotations

import difflib
import re
from typing import Any

import pandas as pd

# Keyword groups ordered by specificity — checked in order
_KEYWORD_GROUPS: list[tuple[str, list[str]]] = [
    ("location", [
        "locid", "loc_id", "plantid", "plant_id",
        "plant", "location", "site", "facility",
        "warehouse", "depot", "wh", "loc",
    ]),
    ("product", [
        "prdid", "prd_id", "productid", "prod_id", "matnr",
        "material", "product", "article", "item", "sku",
        "part", "matl", "mat", "prd", "prod",
    ]),
    ("period", [
        "periodid", "period_id", "calmonth", "cal_month",
        "period", "date", "week", "month", "year",
        "bucket", "horizon", "snap", "dt", "wk", "per",
    ]),
    ("quantity", [
        "fqty", "tqty", "openqty", "planqty",
        "qty", "quantity", "volume", "vol",
        "demand", "supply", "forecast", "sales",
        "amount", "value", "units", "stock", "count",
    ]),
]


def _norm(col: str) -> str:
    """Strip non-alphanumeric chars and lowercase for robust matching."""
    return re.sub(r"[^a-z0-9]", "", col.lower().strip())


def _classify(col: str) -> str | None:
    """Return the logical type of a column using keyword matching."""
    n = _norm(col)
    for group_name, keywords in _KEYWORD_GROUPS:
        for kw in keywords:
            if kw == n or n.startswith(kw) or n.endswith(kw) or kw in n:
                return group_name
    return None


def _fuzzy_match(src: str, candidates: list[str]) -> str | None:
    """Return the best fuzzy-matched candidate for src, or None."""
    if not candidates:
        return None
    ns = _norm(src)
    nc = [_norm(c) for c in candidates]
    matches = difflib.get_close_matches(ns, nc, n=1, cutoff=0.45)
    if matches:
        return candidates[nc.index(matches[0])]
    return None


def auto_map_columns(
    source_df: pd.DataFrame,
    target_df: pd.DataFrame,
) -> dict[str, Any]:
    """
    Intelligently map source columns to target columns.

    Strategy (in order of priority):
      1. Keyword classification match (e.g. 'Plant' → location, 'Qty' → quantity)
      2. Fuzzy string similarity match for unclassified columns
      3. Positional fallback for any remaining unmatched columns
      4. Data-type inference to detect quantity columns that keywords missed

    Returns:
        {
          "mapping": <ColumnMapper-compatible dict>,
          "display": [{"logical", "source_col", "target_col", "role"}, ...]
        }
    """
    src_cols = source_df.columns.tolist()
    tgt_cols = target_df.columns.tolist()

    src_types = {c: _classify(c) for c in src_cols}
    tgt_types = {c: _classify(c) for c in tgt_cols}

    pairs: list[tuple[str, str, str]] = []  # (source_col, target_col, logical_type)
    used_src: set[str] = set()
    used_tgt: set[str] = set()

    # ── Pass 1: keyword classification match ──────────────────────────────────
    for group_name, _ in _KEYWORD_GROUPS:
        src_group = [c for c in src_cols if src_types[c] == group_name and c not in used_src]
        tgt_group = [c for c in tgt_cols if tgt_types[c] == group_name and c not in used_tgt]
        for sc, tc in zip(src_group, tgt_group):
            pairs.append((sc, tc, group_name))
            used_src.add(sc)
            used_tgt.add(tc)

    # ── Pass 2: fuzzy match remaining unclassified columns ────────────────────
    remaining_tgt = [c for c in tgt_cols if c not in used_tgt]
    for sc in src_cols:
        if sc in used_src:
            continue
        match = _fuzzy_match(sc, remaining_tgt)
        if match:
            logical = src_types.get(sc) or tgt_types.get(match) or "unknown"
            pairs.append((sc, match, logical))
            used_src.add(sc)
            remaining_tgt.remove(match)

    # ── Pass 3: positional fallback for any still-unmatched ───────────────────
    remaining_src = [c for c in src_cols if c not in used_src]
    for sc, tc in zip(remaining_src, list(remaining_tgt)):
        logical = src_types.get(sc) or tgt_types.get(tc) or "unknown"
        pairs.append((sc, tc, logical))

    # ── Pass 4: re-classify "unknown" pairs using numeric data-type inference ─
    has_qty = any(lt == "quantity" for _, _, lt in pairs)
    if not has_qty:
        for i, (sc, tc, lt) in enumerate(pairs):
            src_numeric_ratio = pd.to_numeric(source_df[sc], errors="coerce").notna().mean()
            tgt_numeric_ratio = pd.to_numeric(target_df[tc], errors="coerce").notna().mean()
            if src_numeric_ratio > 0.5 and tgt_numeric_ratio > 0.5:
                pairs[i] = (sc, tc, "quantity")
                break  # promote only the most numeric pair

    # ── Build output ──────────────────────────────────────────────────────────
    key_fields = [
        {"source_col": sc, "target_col": tc}
        for sc, tc, lt in pairs
        if lt != "quantity"
    ]
    compare_fields = [
        {"source_col": sc, "target_col": tc}
        for sc, tc, lt in pairs
        if lt == "quantity"
    ]

    display = [
        {
            "logical": lt.replace("_", " ").title(),
            "source_col": sc,
            "target_col": tc,
            "role": "📊 Compare" if lt == "quantity" else "🔑 Key",
        }
        for sc, tc, lt in pairs
    ]

    return {
        "mapping": {
            "key_fields": key_fields,
            "compare_fields": compare_fields,
            "options": {"case_insensitive": True, "trim_whitespace": True},
        },
        "display": display,
    }
