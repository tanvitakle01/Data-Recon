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
from dataclasses import dataclass, field as dc_field
from typing import Any

import pandas as pd

from backend.recon_engine.models.contract import (
    PERIOD_AGGREGATIONS,
    AggregationType,
    TransformationContract,
)
from backend.recon_engine.models.value_mapping import AUTO_APPLY_CONFIDENCE
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
    # Rows dropped by the Value Mapping stage (MEDIUM/NONE/OUT_OF_SCOPE value
    # matches, missing key-field values, or values with no deterministic match
    # record), aggregated per distinct (field, source_value) — never a silent
    # drop. Only VERY_HIGH/HIGH matches ever reach the shadow / join.
    held_out: list[dict[str, Any]] = dc_field(default_factory=list)


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    return str(value).strip() in ("", "None", "nan", "NaT")


def _expand_multi_candidate_rows(
    df: pd.DataFrame, keep_mask: pd.Series, field: str, expand: dict[Any, list[str]]
) -> tuple[pd.DataFrame, pd.Series]:
    """Duplicate each row in ``expand`` once per candidate target value.

    A source value can carry more than one verified candidate (see
    ``value_pairing.pipeline`` module docstring) — rather than picking one,
    every candidate gets its own shadow row (identical in every other column,
    same lineage position) so the join/compare stage can let real record-level
    date + quantity agreement decide which candidate actually matches. A
    candidate that doesn't correspond to any real record simply produces no
    Match for its duplicate row.
    """
    if not expand:
        return df, keep_mask

    pieces: list[pd.DataFrame] = []
    keep_pieces: list[pd.Series] = []
    for idx in df.index:
        targets = expand.get(idx)
        if targets is None:
            pieces.append(df.loc[[idx]])
            keep_pieces.append(pd.Series([keep_mask.at[idx]]))
            continue
        block = pd.concat([df.loc[[idx]]] * len(targets), ignore_index=True)
        block[field] = targets
        pieces.append(block)
        keep_pieces.append(pd.Series([keep_mask.at[idx]] * len(targets)))

    new_df = pd.concat(pieces, ignore_index=True)
    new_keep_mask = pd.concat(keep_pieces, ignore_index=True)
    new_keep_mask.index = new_df.index
    return new_df, new_keep_mask


def _apply_value_mappings(
    df: pd.DataFrame, contract: TransformationContract
) -> tuple[pd.DataFrame, pd.Series, list[dict[str, Any]]]:
    """Apply ``contract.value_mappings`` + business-key completeness to ``df``.

    For every ``business_key`` field:
      * If it has a matching :class:`~backend.recon_engine.models.value_mapping.ValueMapping`:
        VERY_HIGH/HIGH matches replace the value in place (the executable
        transform) and proceed to the join. When a source value has MORE THAN
        ONE accepted (VERY_HIGH/HIGH) candidate, the row is duplicated once per
        candidate (see :func:`_expand_multi_candidate_rows`) rather than
        picking a winner — reconciliation's per-record compare is the real
        arbiter. Every other tier — MEDIUM, NONE, OUT_OF_SCOPE, no match
        record at all — is held out: the row never reaches the join/compare
        stage, and is never rejoined on its original, unresolved value (which
        would silently reintroduce false "Missing in Target" noise). There is
        no review workflow; a MEDIUM match is simply not confident enough to
        apply.
      * Otherwise (no deterministic value mapping for this field — e.g. a date
        key like ``RequestedDeliveryDate``): only a completeness check runs —
        null/blank values can't form a business key, so those rows are held
        out the same way, for the same "never silently drop, never silently
        keep" reason.

    Returns ``(df, keep_mask, held_out)``. Row count only ever grows here (via
    multi-candidate expansion) — the caller applies ``keep_mask`` to drop the
    held-out rows.
    """
    df = df.copy()
    df = df.reset_index(drop=True)
    keep_mask = pd.Series(True, index=df.index)
    held_out: list[dict[str, Any]] = []
    value_mapping_by_field = {vm.source_field: vm for vm in contract.value_mappings}

    for bk in contract.business_key:
        source_field = bk.source_field
        if source_field not in df.columns:
            continue
        col = df[source_field]

        vm = value_mapping_by_field.get(source_field)
        if vm is None:
            blank_mask = col.map(_is_blank)
            if blank_mask.any():
                held_out.append(
                    {
                        "field": source_field,
                        "target_field": bk.target_field,
                        "source_value": None,
                        "confidence": None,
                        "rule": "key_completeness",
                        "reason": f"Missing required key field '{source_field}'.",
                        "row_count": int(blank_mask.sum()),
                    }
                )
            keep_mask &= ~blank_mask
            continue

        matches_by_value: dict[str, list[Any]] = {}
        for m in vm.matches:
            matches_by_value.setdefault(m.source_value, []).append(m)

        hold_reasons: dict[str, dict[str, Any]] = {}
        hold_mask = pd.Series(False, index=df.index)
        expand_rows: dict[Any, list[str]] = {}

        for idx, raw_val in col.items():
            if _is_blank(raw_val):
                bucket = hold_reasons.setdefault(
                    "__null__",
                    {
                        "field": source_field,
                        "target_field": vm.target_field,
                        "source_value": None,
                        "confidence": None,
                        "rule": "key_completeness",
                        "reason": f"Missing required key field '{source_field}'.",
                        "row_count": 0,
                    },
                )
                bucket["row_count"] += 1
                hold_mask.at[idx] = True
                continue

            key = str(raw_val)
            ms = matches_by_value.get(key)
            if not ms:
                bucket = hold_reasons.setdefault(
                    key,
                    {
                        "field": source_field,
                        "target_field": vm.target_field,
                        "source_value": key,
                        "confidence": None,
                        "rule": "unclassified",
                        "reason": (
                            f"No deterministic value mapping recorded for {key!r} — "
                            "run Deterministic Mapping again to classify it."
                        ),
                        "row_count": 0,
                    },
                )
                bucket["row_count"] += 1
                hold_mask.at[idx] = True
                continue

            accepted = [
                m for m in ms if m.confidence in AUTO_APPLY_CONFIDENCE and m.target_value is not None
            ]
            if not accepted:
                m = ms[0]  # MEDIUM / NONE / OUT_OF_SCOPE — held out, never rejoined unresolved.
                bucket = hold_reasons.setdefault(
                    key,
                    {
                        "field": source_field,
                        "target_field": vm.target_field,
                        "source_value": key,
                        "target_value": m.target_value,
                        "confidence": m.confidence.value,
                        "rule": m.rule,
                        "reason": m.evidence,
                        "row_count": 0,
                    },
                )
                bucket["row_count"] += 1
                hold_mask.at[idx] = True
            elif len(accepted) == 1:
                df.at[idx, source_field] = accepted[0].target_value
            else:
                expand_rows[idx] = [m.target_value for m in accepted]

        held_out.extend(hold_reasons.values())
        keep_mask &= ~hold_mask

        if expand_rows:
            df, keep_mask = _expand_multi_candidate_rows(df, keep_mask, source_field, expand_rows)

    return df, keep_mask, held_out


def build_shadow_source(
    contract: TransformationContract, raw_source_df: pd.DataFrame
) -> ShadowBuildResult:
    """Execute the contract to produce the Shadow_Source, in a fixed pipeline:

        0. Value Mapping   (contract.value_mappings + key completeness) —
           auto-apply confident (VERY_HIGH/HIGH) identifier value maps; hold
           out everything else (MEDIUM/NONE/OUT_OF_SCOPE, no match record, or
           a missing key field) so it never reaches the join.
        1. Filters        (FILTER ops)          — drop rows on RAW source values
        2. Transformations (TRANSFORM ops)      — reshape values, in order
        3. Aggregations   (AGGREGATE ops, then ``aggregation_rules``)

    Ordering is enforced here rather than trusting the order the compiler emitted
    operations, so "value-map before filter before transform before aggregate"
    always holds. Relative order within a stage is preserved. Compare ops are
    ignored here — the reconciler uses them. Raw_Source is never mutated.
    """
    df = raw_source_df.reset_index(drop=True).copy()
    df[POS_COL] = range(len(df))
    # pos value -> list of originating raw row ids
    lineage: dict[int, list[int]] = {i: [i] for i in range(len(df))}

    # ── 0. Value Mapping + key completeness ──
    held_out: list[dict[str, Any]] = []
    if contract.business_key:
        df, keep_mask, held_out = _apply_value_mappings(df, contract)
        df = df.loc[keep_mask].reset_index(drop=True)

    # Bucket ops by stage, preserving relative order within each stage.
    # Disabled steps are authored but inert — skipped entirely so they neither
    # run nor affect the shadow (the recipe editor toggles them without deleting).
    filters, transforms, aggregates = [], [], []
    for op in contract.operations:
        if not getattr(op, "enabled", True):
            continue
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
    return ShadowBuildResult(shadow_df=final, lineage=lineage_rows, held_out=held_out)


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
