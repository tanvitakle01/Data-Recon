from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Any, Optional

import pandas as pd

from backend.excel_comparator.core.auto_mapper import auto_map_columns  # type: ignore
from backend.excel_comparator.core.comparator import ExcelComparator  # type: ignore
from backend.excel_comparator.core.loader import load_excel  # type: ignore
from backend.excel_comparator.core.mapper import ColumnMapper  # type: ignore
from backend.excel_comparator.core.writer import write_annotated_excel  # type: ignore
from backend.excel_comparator.utils.helpers import classify_remark, build_summary  # type: ignore


@dataclass
class ReconcileArtifacts:
    annotated_df: pd.DataFrame
    summary: dict[str, int]


def reconcile_frames(source_df: pd.DataFrame, target_df: pd.DataFrame, mapping: dict[str, Any]) -> ReconcileArtifacts:
    mapper = ColumnMapper(mapping)
    mapper.validate(source_df, target_df)

    comparator = ExcelComparator(source_df, target_df, mapper)
    annotated_df, summary = comparator.run([1, 2, 3, 4])
    return ReconcileArtifacts(annotated_df=annotated_df, summary=summary)


def build_match_unmatch_records(annotated_df: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if "Remarks" not in annotated_df.columns:
        return [], []

    df = annotated_df.copy()
    df["Scenario"] = df["Remarks"].apply(classify_remark)

    matched = df[df["Scenario"] == "MATCHED"].drop(columns=["Scenario"]).copy()
    unmatched = df[df["Scenario"] != "MATCHED"].drop(columns=["Scenario"]).copy()

    matched_records = matched.astype(object).where(pd.notna(matched), None).to_dict(orient="records")
    unmatched_records = unmatched.astype(object).where(pd.notna(unmatched), None).to_dict(orient="records")
    return matched_records, unmatched_records


def compute_reconcile_summary(summary: dict[str, int]) -> dict[str, Any]:
    total = int(summary.get("total_rows", 0))
    matched = int(summary.get("matched", 0))
    unmatched = total - matched
    match_pct = float(matched / total * 100) if total else 0.0

    return {
        "total_records": total,
        "matched": matched,
        "unmatched": unmatched,
        "match_percentage": match_pct,
        "qty_mismatch": int(summary.get("qty_mismatch", 0)),
        "missing_in_target": int(summary.get("missing_in_target", 0)),
        "extra_in_target": int(summary.get("extra_in_target", 0)),
    }


def write_annotated_excel_bytes(
    annotated_df: pd.DataFrame,
    original_target_bytes: bytes,
    sheet_name: str,
) -> bytes:
    output = write_annotated_excel(
        annotated_df,
        original_target_path=BytesIO(original_target_bytes),
        sheet_name=sheet_name,
    )
    return output.getvalue()

