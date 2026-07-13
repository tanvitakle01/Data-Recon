"""Deterministic contract executor: Raw_Source -> Shadow_Source.

Applies a contract's operations, in order, to a raw source frame to derive a
Shadow_Source. Raw_Source is never mutated (the frame is copied first). Each
shadow row carries a lineage column referencing the raw row id(s) it derives
from — mandatory for auditability.

This is deterministic execution driven purely by contract *data*: it looks up
each named operation in the allow-listed registry and calls the hand-written
implementation. No code from the contract is ever executed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pandas as pd

from backend.recon_engine.models.contract import (
    PERIOD_AGGREGATIONS,
    AggregationType,
    TransformationContract,
)
from backend.recon_engine.operations import get_operation
from backend.recon_engine.operations.registry import OperationKind
from backend.recon_engine.storage import frames

# Pandas aggregation function for each measure aggregation type.
_MEASURE_FUNC: dict[AggregationType, str] = {
    AggregationType.SUM: "sum",
    AggregationType.COUNT: "count",
    AggregationType.AVERAGE: "mean",
    AggregationType.MIN: "min",
    AggregationType.MAX: "max",
}
# Numeric coercion is required for these before aggregating.
_NUMERIC_FUNCS = {"sum", "mean", "min", "max"}
# pandas offset alias for each period bucket.
_PERIOD_FREQ: dict[AggregationType, str] = {
    AggregationType.GROUP_BY_DAY: "D",
    AggregationType.GROUP_BY_WEEK: "W",
    AggregationType.GROUP_BY_MONTH: "M",
    AggregationType.GROUP_BY_QUARTER: "Q",
    AggregationType.GROUP_BY_YEAR: "Y",
}

# Reserved column names (double-underscore, dropped from any comparison/join).
POS_COL = "__pos__"
LINEAGE_COL = "__source_row_ids__"


def shadow_fingerprint(shadow_df: pd.DataFrame) -> str:
    """Deterministic content hash of a Shadow_Source, ignoring lineage.

    Used by the Review-Changes checkpoint: the fingerprint shown at review time
    is recomputed at run time and must match, proving the reconciled shadow is
    byte-identical to the one the user approved. The lineage column is dropped
    first so the hash reflects the reviewed *data*, not bookkeeping.
    """
    display = shadow_df.drop(columns=[LINEAGE_COL], errors="ignore")
    return frames.compute_frame_hash(display)


@dataclass
class ShadowBuildResult:
    shadow_df: pd.DataFrame  # includes LINEAGE_COL
    lineage: list[list[int]]  # per shadow row -> raw source row ids


def build_shadow_source(
    contract: TransformationContract, raw_source_df: pd.DataFrame
) -> ShadowBuildResult:
    """Execute the contract to produce the Shadow_Source, in a fixed pipeline:

        1. Filters        (FILTER ops)          — drop rows on RAW source values
        2. Transformations (TRANSFORM ops)      — reshape values, in order
        3. Aggregations   (AGGREGATE ops, then ``aggregation_rules``)

    Ordering is enforced here rather than trusting the order the compiler emitted
    operations, so "filter before transform before aggregate" always holds.
    Relative order within a stage is preserved. Compare ops are ignored here —
    the reconciler uses them. Raw_Source is never mutated.
    """
    df = raw_source_df.reset_index(drop=True).copy()
    df[POS_COL] = range(len(df))
    # pos value -> list of originating raw row ids
    lineage: dict[int, list[int]] = {i: [i] for i in range(len(df))}

    # Bucket ops by stage, preserving relative order within each stage.
    filters, transforms, aggregates = [], [], []
    for op in contract.operations:
        spec = get_operation(op.op)  # KeyError here == not allow-listed
        if spec.kind == OperationKind.FILTER:
            filters.append((spec, op))
        elif spec.kind == OperationKind.TRANSFORM:
            transforms.append((spec, op))
        elif spec.kind == OperationKind.AGGREGATE:
            aggregates.append((spec, op))
        # COMPARE ops: skipped (reconciler-only).

    # ── 1. Filters ──
    for spec, op in filters:
        df = spec.func(df, op.field, op.params)

    # ── 2. Transformations ──
    for spec, op in transforms:
        df = spec.func(df, op.field, op.params)

    # ── 3. Aggregations ──
    for spec, op in aggregates:
        df, lineage = _apply_aggregate(spec.func, op, df, lineage)
    df, lineage = _apply_aggregation_rules(contract, df, lineage)

    final = df.reset_index(drop=True)
    positions = final[POS_COL].tolist()
    lineage_rows = [lineage.get(int(p), []) for p in positions]

    final = final.drop(columns=[POS_COL], errors="ignore")
    final[LINEAGE_COL] = [json.dumps(ids) for ids in lineage_rows]
    return ShadowBuildResult(shadow_df=final, lineage=lineage_rows)


def _bucket_period(series: pd.Series, agg: AggregationType) -> pd.Series:
    """Bucket a date column to a period start date (canonical YYYY-MM-DD).

    e.g. GROUP_BY_MONTH turns 2025-08-19 into 2025-08-01. Unparseable values
    become null. Emitting the period *start* aligns with IBP period-start dates
    so the aggregated key can match the target's KEYFIGUREDATE.
    """
    dt = pd.to_datetime(series, errors="coerce")
    start = dt.dt.to_period(_PERIOD_FREQ[agg]).dt.start_time
    labelled = start.dt.strftime("%Y-%m-%d")
    return labelled.where(dt.notna(), None)


def _apply_aggregation_rules(
    contract: TransformationContract, df: pd.DataFrame, lineage: dict[int, list[int]]
):
    """Apply structured ``aggregation_rules``: bucket period fields, then group
    by the business key (+ any period field) and aggregate the measures.

    Lineage collapses to the group level, mirroring :func:`_apply_aggregate`.
    """
    rules = contract.aggregation_rules
    if not rules:
        return df, lineage

    # 1. Period bucketing turns a date field into a coarse grouping dimension.
    period_fields: list[str] = []
    for rule in rules:
        if rule.aggregation in PERIOD_AGGREGATIONS and rule.source_field in df.columns:
            df = df.copy()
            df[rule.source_field] = _bucket_period(df[rule.source_field], rule.aggregation)
            period_fields.append(rule.source_field)

    measures = {
        rule.source_field: _MEASURE_FUNC[rule.aggregation]
        for rule in rules
        if rule.aggregation in _MEASURE_FUNC and rule.source_field in df.columns
    }

    # 2. Group keys = business keys + period fields (deduped, existing only).
    key_fields = [k.source_field for k in contract.business_key]
    group_keys = [
        c for c in dict.fromkeys([*key_fields, *period_fields]) if c in df.columns
    ]
    if not group_keys:
        # No grouping dimension — nothing to aggregate against; leave df as-is.
        return df, lineage

    # 3. Keep only group keys + measures + compare fields; everything else is
    #    incidental and dropped by the aggregation.
    compare_src = [c.source_field for c in contract.compare_fields]
    keep = list(dict.fromkeys([*group_keys, *measures.keys(), *compare_src]))

    agg_spec: dict[str, str] = {}
    for col in keep:
        if col in group_keys or col not in df.columns:
            continue
        func = measures.get(col, "first")
        if func in _NUMERIC_FUNCS:
            df = df.copy()
            df[col] = pd.to_numeric(df[col], errors="coerce")
        agg_spec[col] = func

    grouped_pos = df.groupby(group_keys, dropna=False)[POS_COL].apply(list)
    result = df.groupby(group_keys, dropna=False, as_index=False).agg(agg_spec)

    new_lineage: dict[int, list[int]] = {}
    for new_i in range(len(result)):
        row = result.iloc[new_i]
        key = tuple(row[c] for c in group_keys)
        lookup_key = key if len(group_keys) > 1 else key[0]
        try:
            positions = grouped_pos.loc[lookup_key]
        except KeyError:
            positions = []
        raw_ids: list[int] = []
        for p in positions:
            raw_ids.extend(lineage.get(int(p), []))
        new_lineage[new_i] = raw_ids

    result[POS_COL] = range(len(result))
    return result, new_lineage


def _apply_aggregate(func, op, df: pd.DataFrame, lineage: dict[int, list[int]]):
    """Run an aggregate op while collapsing lineage to the group level."""
    by = list(op.params["by"])
    grouped = df.groupby(by, dropna=False)[POS_COL].apply(list)

    result = func(df, op.field, op.params).reset_index(drop=True)

    new_lineage: dict[int, list[int]] = {}
    for new_i in range(len(result)):
        row = result.iloc[new_i]
        key = tuple(row[c] for c in by)
        lookup_key = key if len(by) > 1 else key[0]
        try:
            group_positions = grouped.loc[lookup_key]
        except KeyError:
            group_positions = []
        raw_ids: list[int] = []
        for p in group_positions:
            raw_ids.extend(lineage.get(int(p), []))
        new_lineage[new_i] = raw_ids

    result[POS_COL] = range(len(result))
    return result, new_lineage
