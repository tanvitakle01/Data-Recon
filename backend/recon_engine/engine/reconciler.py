"""Deterministic reconciler: Shadow_Source FULL OUTER JOIN Raw_Target.

Joins on the contract's business key, applies per-field tolerances via the
allow-listed compare operations, and classifies every record into one of four
terminal buckets:

    match | mismatch | missing_in_source | missing_in_target

Each side is first deduplicated independently on the business key (keep first);
duplicate rows are dropped silently. Records that can't be verified (missing
compare field, unset tolerance) fall into ``mismatch`` — there is no separate
exception path.

No LLM is involved at runtime. Behaviour is fully determined by the approved
contract + the two immutable inputs, so a run is reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from backend.recon_engine.engine.executor import LINEAGE_COL, pair_id_col
from backend.recon_engine.models.contract import MatchType, TransformationContract
from backend.recon_engine.models.results import RecordClass, ReconciliationSummary
from backend.recon_engine.operations import get_operation


@dataclass
class ReconcileResult:
    detail_df: pd.DataFrame
    summary: ReconciliationSummary


# Every key ``_record()`` ever puts in a row dict, in that same order — passed
# explicitly to ``pd.DataFrame`` below so a batch with zero output records
# still gets a properly-shaped (0-row, correctly-named) frame rather than
# ``pd.DataFrame([])``'s bare 0-row/0-COLUMN frame (see ``storage.frames.
# append_frame``'s docstring on why a 0-column frame is dangerous downstream).
_DETAIL_COLUMNS = ["business_key", "classification", "detail", "source_row_ids", "field_diffs", "pair_ids"]


def _normalise_scalar(value: Any, options: dict[str, Any]) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    s = str(value)
    if options.get("trim_whitespace", True):
        s = s.strip()
    if options.get("case_insensitive", True):
        s = s.casefold()
    return s


def _build_key(df: pd.DataFrame, fields: list[str], options: dict[str, Any]) -> pd.Series:
    if df.empty:
        return pd.Series([], dtype=str)
    parts = [df[f].map(lambda v: _normalise_scalar(v, options)) for f in fields]
    key = parts[0]
    for p in parts[1:]:
        key = key.str.cat(p, sep="|")
    return key


def reconcile(
    contract: TransformationContract,
    shadow_df: pd.DataFrame,
    raw_target_df: pd.DataFrame,
) -> ReconcileResult:
    options = contract.options or {}
    src_key_fields = [k.source_field for k in contract.business_key]
    tgt_key_fields = [k.target_field for k in contract.business_key]

    shadow = shadow_df.reset_index(drop=True).copy()
    target = raw_target_df.reset_index(drop=True).copy()

    shadow["__key__"] = _build_key(shadow, src_key_fields, options)
    target["__key__"] = _build_key(target, tgt_key_fields, options)

    records: list[dict[str, Any]] = []

    # ── deduplicate each side independently, keeping the first record ─────────
    # If a side carries several rows with the same business key we keep only the
    # first for reconciliation; the remaining duplicates are dropped silently.
    shadow_u = shadow.drop_duplicates(subset="__key__", keep="first").set_index("__key__")
    target_u = target.drop_duplicates(subset="__key__", keep="first").set_index("__key__")

    shadow_keys = set(shadow_u.index)
    target_keys = set(target_u.index)

    both = shadow_keys & target_keys
    source_only = shadow_keys - target_keys
    target_only = target_keys - shadow_keys

    # ── present on both sides: compare -> match / mismatch / exception ───────
    for key in both:
        s_row = shadow_u.loc[key]
        t_row = target_u.loc[key]
        cls, detail, field_diffs = _compare_row(contract, s_row, t_row)
        records.append(
            _record(
                cls,
                key=key,
                detail=detail,
                lineage=s_row.get(LINEAGE_COL),
                field_diffs=field_diffs,
                pair_ids=_extract_pair_ids(s_row, src_key_fields),
            )
        )

    # ── shadow only ──────────────────────────────────────────────────────────
    for key in source_only:
        s_row = shadow_u.loc[key]
        records.append(
            _record(
                RecordClass.MISSING_IN_TARGET,
                key=key,
                detail="Business key present in source, absent in target.",
                lineage=s_row.get(LINEAGE_COL),
                pair_ids=_extract_pair_ids(s_row, src_key_fields),
            )
        )

    # ── target only ────────────────────────────────────────────────────────
    for key in target_only:
        records.append(
            _record(
                RecordClass.MISSING_IN_SOURCE,
                key=key,
                detail="Business key present in target, absent in source.",
                lineage=None,
            )
        )

    detail_df = pd.DataFrame(records, columns=_DETAIL_COLUMNS)
    counts = (
        detail_df["classification"].value_counts().to_dict() if not detail_df.empty else {}
    )
    summary = ReconciliationSummary.from_counts({str(k): int(v) for k, v in counts.items()})
    return ReconcileResult(detail_df=detail_df, summary=summary)


def _extract_pair_ids(s_row: pd.Series, source_key_fields: list[str]) -> dict[str, str]:
    """Every business-key field's ``pair_id`` riding along on this shadow row
    (see ``engine.executor``'s ``__pair_id_<field>__`` reserved columns) —
    keyed by SOURCE field name, same convention as
    ``models.results.excluded_unmapped_counts``. Empty when the field had no
    value mapping (e.g. a date key) or the row predates this column existing."""
    pair_ids: dict[str, str] = {}
    for field in source_key_fields:
        value = s_row.get(pair_id_col(field))
        if isinstance(value, str) and value:
            pair_ids[field] = value
    return pair_ids


def _record(
    cls: RecordClass,
    *,
    key: str,
    detail: str,
    lineage: Any,
    field_diffs: list[dict[str, Any]] | None = None,
    pair_ids: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "business_key": key,
        "classification": cls.value,
        "detail": detail,
        "source_row_ids": lineage if isinstance(lineage, str) else None,
        "field_diffs": field_diffs or [],
        "pair_ids": pair_ids or {},
    }


def _jsonable_scalar(value: Any) -> Any:
    """Coerce a cell value to a JSON-serialisable scalar (native / str / None)."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (bool, int, float, str)):
        return value
    item = getattr(value, "item", None)  # numpy scalar -> python scalar
    if callable(item):
        try:
            return value.item()
        except (ValueError, TypeError):
            pass
    return str(value)


def _to_number(value: Any) -> float | None:
    """Parse a single value as a float the way the compare ops do, else None."""
    num = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return None if pd.isna(num) else float(num)


def _compare_row(
    contract: TransformationContract, s_row: pd.Series, t_row: pd.Series
) -> tuple[RecordClass, str, list[dict[str, Any]]]:
    """Compare all compare fields for one matched key.

    Returns the classification, a flattened human-readable detail string (kept
    for backward compatibility), and a structured list of per-field diffs for
    the fields that differ. Each diff carries the field mapping, the raw source
    and target values, the numeric ``delta``/``variance_pct`` (when both sides
    parse as numbers), and the tolerance in effect — the evidence the workbook
    and insights layers expand into per-field rows and quantity variance.
    """
    if not contract.compare_fields:
        return RecordClass.MATCH, "Key match (no compare fields).", []

    mismatches: list[str] = []
    field_diffs: list[dict[str, Any]] = []
    for cf in contract.compare_fields:
        if cf.source_field not in s_row.index or cf.target_field not in t_row.index:
            # Field the contract expects is absent at runtime — can't verify it,
            # so treat as a mismatch rather than a match.
            mismatches.append(
                f"Compare field missing at runtime: {cf.source_field}/{cf.target_field}."
            )
            continue

        params: dict[str, Any] = {"options": contract.options}
        if cf.match_type == MatchType.TOLERANCE:
            if cf.tolerance is None:
                # Misconfigured tolerance — unverifiable, so treat as a mismatch.
                mismatches.append(f"Tolerance not set for '{cf.source_field}'.")
                continue
            op_name = "tolerance_match"
            params["tolerance"] = cf.tolerance
        else:
            op_name = "exact_match"

        func = get_operation(op_name).func
        src_val = s_row[cf.source_field]
        tgt_val = t_row[cf.target_field]
        matched = bool(func(pd.Series([src_val]), pd.Series([tgt_val]), params).iloc[0])
        if matched:
            continue

        mismatches.append(f"{cf.source_field}: expected {src_val!r}, got {tgt_val!r}")

        src_num = _to_number(src_val)
        tgt_num = _to_number(tgt_val)
        delta = None
        variance_pct = None
        if src_num is not None and tgt_num is not None:
            delta = src_num - tgt_num
            if tgt_num != 0:
                variance_pct = round((delta / tgt_num) * 100.0, 2)
        field_diffs.append(
            {
                "field": cf.source_field,
                "source_field": cf.source_field,
                "target_field": cf.target_field,
                "source_value": _jsonable_scalar(src_val),
                "target_value": _jsonable_scalar(tgt_val),
                "match_type": cf.match_type.value,
                "tolerance": cf.tolerance,
                "matched": False,
                "delta": delta,
                "variance_pct": variance_pct,
            }
        )

    if mismatches:
        return RecordClass.MISMATCH, "; ".join(mismatches), field_diffs
    return RecordClass.MATCH, "All compare fields within tolerance.", []
