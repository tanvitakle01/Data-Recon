"""Normalizes a reconciliation run's own results — or an uploaded results
workbook in the same shape — into one common schema, so `facts.py` never
needs to know which of the two it came from.

Both paths converge on the exact column layout `service.
_export_columns_for_contract` already defines for the "All Records" sheet of
the downloadable comparison workbook: business-key column(s), "Status", then
one (source, target, delta) triplet per compare field, then traceability
columns. That layout is this codebase's own export schema — the single
source of truth for what a record "looks like" — never re-invented here,
only read back.

The exported "Status" column collapses two raw classifications
(`missing_in_target` / `missing_in_source`) into one "MISMATCH" bucket (see
`service._STATUS_BY_CLASS`). A live run still has the precise
`classification` column to recover that split exactly; an uploaded workbook
does not, so it infers the split from which side's raw column is blank for a
mismatch row (see `_infer_status`) — the same blank-cell signal
`service._unified`/`_original_raw_value` produce by construction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

import openpyxl
import pandas as pd

from backend.recon_engine import service as recon_service

STATUS_MATCH = "match"
STATUS_QTY_MISMATCH = "quantity_mismatch"
STATUS_MISSING_IN_TARGET = "missing_in_target"
STATUS_MISSING_IN_SOURCE = "missing_in_source"

STATUS_ORDER = [STATUS_MATCH, STATUS_QTY_MISMATCH, STATUS_MISSING_IN_TARGET, STATUS_MISSING_IN_SOURCE]
STATUS_LABELS: dict[str, str] = {
    STATUS_MATCH: "Match",
    STATUS_QTY_MISMATCH: "Quantity Mismatch",
    STATUS_MISSING_IN_TARGET: "Missing in Target",
    STATUS_MISSING_IN_SOURCE: "Extra in Target",
}
_CLASSIFICATION_TO_STATUS = {
    "match": STATUS_MATCH,
    "mismatch": STATUS_QTY_MISMATCH,
    "missing_in_target": STATUS_MISSING_IN_TARGET,
    "missing_in_source": STATUS_MISSING_IN_SOURCE,
}

# Generic column-name patterns for the dimensions worth ranking hotspots by.
# Any business-key or compare field whose name matches one of these is
# surfaced as a hotspot dimension automatically, on top of the given labels -
# not limited to only Plant/Material/Date.
_DIMENSION_PATTERNS: dict[str, tuple[str, ...]] = {
    "Plant": ("plant", "werks", "location", "storagelocation"),
    "Material": ("material", "matnr", "product", "item", "sku"),
    "Date": ("date", "deliverydate", "postingdate", "documentdate", "reqdeliverydate"),
}
_ORIGINAL_SUFFIX = " (Original)"
_PAIRED_SUFFIX = " (Paired)"


def _bare_label(column: str) -> str:
    if column.endswith(_ORIGINAL_SUFFIX):
        return column[: -len(_ORIGINAL_SUFFIX)]
    if column.endswith(_PAIRED_SUFFIX):
        return column[: -len(_PAIRED_SUFFIX)]
    return column


def _detect_dimension_label(column: str) -> str | None:
    bare = _bare_label(column).lower().replace(" ", "").replace("_", "")
    for label, patterns in _DIMENSION_PATTERNS.items():
        if any(p in bare for p in patterns):
            return label
    return None


def _dimension_columns(columns: list[str]) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for col in columns:
        label = _detect_dimension_label(col)
        if label is None:
            continue
        found.setdefault(label, []).append(col)
    return found


def _column_sections(columns: list[str]) -> tuple[list[str], list[tuple[str, str]], list[str]]:
    """Split an All-Records-shaped column list into (key columns, compare
    field (source, target) pairs, delta column names) using the fixed layout
    `service._export_columns_for_contract` always writes: key columns, then
    "Status", then repeating (source, target, delta) triplets per compare
    field, then traceability. Works identically whether `columns` came from
    a live contract or was read back off an uploaded workbook's header row.
    """
    try:
        status_idx = columns.index("Status")
    except ValueError:
        return columns, [], []
    try:
        traceability_idx = columns.index("Run ID")
    except ValueError:
        traceability_idx = len(columns)
    key_cols = columns[:status_idx]
    compare_section = columns[status_idx + 1 : traceability_idx]
    n_triplets = len(compare_section) // 3
    compare_pairs = [(compare_section[i * 3], compare_section[i * 3 + 1]) for i in range(n_triplets)]
    delta_cols = [compare_section[i * 3 + 2] for i in range(n_triplets)]
    return key_cols, compare_pairs, delta_cols


@dataclass
class NormalizedRecon:
    run_id: str | None
    upload_id: str | None
    total: int
    records_df: pd.DataFrame
    mapping_df: pd.DataFrame
    delta_columns: list[str]
    compare_pairs: list[tuple[str, str]]
    dimension_columns: dict[str, list[str]] = field(default_factory=dict)
    key_columns: list[str] = field(default_factory=list)


# ── from a persisted run ─────────────────────────────────────────────────────


def from_run(run_id: str) -> NormalizedRecon:
    recon_service.init_storage()
    run = recon_service.run_store.get_run(run_id)
    if run is None:
        raise KeyError(f"Unknown run '{run_id}'.")
    result = recon_service.result_store.get_result_for_run(run_id)
    if result is None:
        raise KeyError(f"No reconciliation result found for run '{run_id}'.")

    contract = recon_service.contract_store.get_contract(run.contract_id, run.contract_version)
    contract = recon_service._effective_contract(contract, run_id)

    enriched = recon_service.build_enriched_detail(run_id)
    columns = recon_service._export_columns_for_contract(contract)
    key_cols, compare_pairs, delta_cols = _column_sections(columns)

    if enriched.empty:
        records_df = pd.DataFrame(columns=[*columns, "__status__", "Status Detail"])
    else:
        records_df = enriched.copy()
        records_df["__status__"] = (
            records_df["classification"].map(_CLASSIFICATION_TO_STATUS).fillna(STATUS_QTY_MISMATCH)
        )
        records_df["Status Detail"] = records_df["__status__"].map(STATUS_LABELS)
        keep = [c for c in columns if c in records_df.columns] + ["__status__", "Status Detail"]
        records_df = records_df[keep]

    mapping_rows: list[dict[str, Any]] = []
    for sf, tf, vm in recon_service._business_key_export_specs(contract):
        if vm is None:
            continue
        label = f"{sf} → {tf}"
        for m in vm.matches:
            paired = m.target_value is not None
            siblings = [c for c in (m.candidates or []) if c != m.target_value]
            corroboration = ""
            if siblings:
                corroboration = (
                    "Dates overlap"
                    if m.corroboration is True
                    else "No date overlap" if m.corroboration is False else "No signal"
                )
            mapping_rows.append(
                {
                    "Mapping": label,
                    "Source Value": m.source_value,
                    "Target Value": m.target_value,
                    "Status": "Paired" if paired else "Unpaired",
                    "Confidence": recon_service._CONFIDENCE_LABELS.get(m.confidence.value, m.confidence.value),
                    "Corroboration": corroboration,
                    "Also Candidate For": ", ".join(siblings),
                    "Row Count": m.row_count,
                    "Reason": m.evidence,
                    "Pair ID": m.pair_id,
                }
            )
    mapping_df = pd.DataFrame(mapping_rows, columns=recon_service._MAPPING_DETAIL_COLUMNS)

    return NormalizedRecon(
        run_id=run_id,
        upload_id=None,
        total=int(len(records_df)),
        records_df=records_df,
        mapping_df=mapping_df,
        delta_columns=delta_cols,
        compare_pairs=compare_pairs,
        dimension_columns=_dimension_columns(columns),
        key_columns=key_cols,
    )


# ── from an uploaded results workbook ────────────────────────────────────────

_REQUIRED_SHEETS = ("Summary", "All Records", "Transformations Applied")


class UnrecognizedWorkbookError(ValueError):
    """Raised when an uploaded file isn't a results workbook this app exported."""


def _read_sheet_df(wb: Any, name: str) -> pd.DataFrame:
    ws = wb[name]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return pd.DataFrame()
    header, *data = rows
    header = [str(h) if h is not None else "" for h in header]
    return pd.DataFrame(data, columns=header)


def _is_blank(value: Any) -> bool:
    if isinstance(value, pd.Series):
        # A source/target compare-field pair that happens to share the exact
        # same field name on both sides produces a duplicate column in the
        # exported sheet; `.get()` then returns every match — treat it as
        # blank only if every duplicate is blank.
        return bool(value.map(_is_blank).all())
    if value is None or value == "":
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _infer_status(row: pd.Series, compare_pairs: list[tuple[str, str]], original_cols: list[str]) -> str:
    status = str(row.get("Status") or "").upper()
    if status == "MATCH":
        return STATUS_MATCH
    if status == "QUANTITY MISMATCH":
        return STATUS_QTY_MISMATCH
    # "MISMATCH": infer which side is missing via the blank-cell signal — a
    # compare field's raw source/target column, or a value-mapped key's
    # "(Original)" column, is blank exactly on the side with no row (see
    # service._unified / _original_raw_value).
    for sf, tf in compare_pairs:
        s_blank, t_blank = _is_blank(row.get(sf)), _is_blank(row.get(tf))
        if s_blank and not t_blank:
            return STATUS_MISSING_IN_SOURCE
        if t_blank and not s_blank:
            return STATUS_MISSING_IN_TARGET
    for col in original_cols:
        if _is_blank(row.get(col)):
            return STATUS_MISSING_IN_SOURCE
    # No signal available (no compare fields, no value-mapped keys) — default
    # rather than fabricate a distinction the sheet doesn't carry.
    return STATUS_MISSING_IN_TARGET


def from_workbook(xlsx_bytes: bytes) -> NormalizedRecon:
    try:
        wb = openpyxl.load_workbook(BytesIO(xlsx_bytes), data_only=True)
    except Exception as exc:  # noqa: BLE001
        raise UnrecognizedWorkbookError(f"Not a valid Excel workbook: {exc}") from exc

    missing = [s for s in _REQUIRED_SHEETS if s not in wb.sheetnames]
    if missing:
        raise UnrecognizedWorkbookError(
            "This doesn't look like a reconciliation results workbook — missing sheet(s): "
            + ", ".join(missing)
            + ". Upload the workbook downloaded from a completed reconciliation run."
        )

    records_df = _read_sheet_df(wb, "All Records")
    # The "Transformations Applied" sheet interleaves operation-summary rows
    # with per-value drill-down rows in one flat table — only the drill-down
    # rows carry a "Mapping" label; summary rows leave it blank, which
    # excludes them here without any special-casing needed (a plain column
    # projection, same as the old dedicated "Mapping Details" sheet).
    mapping_df = _read_sheet_df(wb, "Transformations Applied")
    for col in recon_service._MAPPING_DETAIL_COLUMNS:
        if col not in mapping_df.columns:
            mapping_df[col] = None
    mapping_df = mapping_df[mapping_df["Mapping"].notna() & (mapping_df["Mapping"] != "")]

    columns = list(records_df.columns)
    key_cols, compare_pairs, delta_cols = _column_sections(columns)
    original_cols = [c for c in key_cols if c.endswith(_ORIGINAL_SUFFIX)]

    if records_df.empty:
        records_df["__status__"] = pd.Series(dtype=object)
        records_df["Status Detail"] = pd.Series(dtype=object)
    else:
        records_df["__status__"] = records_df.apply(
            lambda r: _infer_status(r, compare_pairs, original_cols), axis=1
        )
        records_df["Status Detail"] = records_df["__status__"].map(STATUS_LABELS)

    return NormalizedRecon(
        run_id=None,
        upload_id=None,
        total=int(len(records_df)),
        records_df=records_df,
        mapping_df=mapping_df,
        delta_columns=delta_cols,
        compare_pairs=compare_pairs,
        dimension_columns=_dimension_columns(columns),
        key_columns=key_cols,
    )
