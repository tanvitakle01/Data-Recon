from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd


def normalise_value(val: Any, case_insensitive: bool = True, trim: bool = True) -> str:
    """Clean a single cell value for safe comparison."""
    if pd.isna(val):
        text = ""
    else:
        text = str(val)

    if trim:
        text = text.strip()
    if case_insensitive:
        text = text.lower()
    return text


def build_composite_key(row: pd.Series, cols: list[str], options: dict[str, Any]) -> str:
    """Build a pipe-delimited composite key from multiple column values."""
    case_insensitive = bool(options.get("case_insensitive", True))
    trim = bool(options.get("trim_whitespace", True))
    parts = [normalise_value(row.get(col), case_insensitive=case_insensitive, trim=trim) for col in cols]
    return "|".join(parts)


def compute_delta(source_val: Any, target_val: Any) -> Any:
    """Return numeric delta if both are numeric, else return 'N/A'."""
    src_num = pd.to_numeric(source_val, errors="coerce")
    tgt_num = pd.to_numeric(target_val, errors="coerce")

    if pd.isna(src_num) or pd.isna(tgt_num):
        return "N/A"
    return src_num - tgt_num


def classify_remark(remark: str) -> str:
    """Map remark text into a scenario label used by UI filters/charts."""
    if not isinstance(remark, str):
        return "Unremarked"

    upper_remark = remark.upper()
    if "QTY MISMATCH" in upper_remark:
        return "QTY MISMATCH"
    if "MATCH" in upper_remark:
        return "MATCHED"
    if "MISSING IN TARGET" in upper_remark:
        return "MISSING IN TARGET"
    if "EXTRA IN TARGET" in upper_remark:
        return "EXTRA IN TARGET"
    return "Unremarked"


def build_summary(annotated_df: pd.DataFrame) -> dict[str, int]:
    """Build scenario-wise counts from the Remarks column."""
    if "Remarks" not in annotated_df.columns:
        return {
            "matched": 0,
            "qty_mismatch": 0,
            "missing_in_target": 0,
            "extra_in_target": 0,
            "total_rows": int(len(annotated_df)),
        }

    remarks = annotated_df["Remarks"].fillna("").astype(str)
    summary = {
        "matched": int(remarks.str.contains(r"MATCH \| Key found in Source", regex=True).sum()),
        "qty_mismatch": int(remarks.str.contains("QTY MISMATCH", regex=False).sum()),
        "missing_in_target": int(remarks.str.contains("MISSING IN TARGET", regex=False).sum()),
        "extra_in_target": int(remarks.str.contains("EXTRA IN TARGET", regex=False).sum()),
        "total_rows": int(len(annotated_df)),
    }
    return summary


def get_output_filename(original_name: str) -> str:
    """Return the output file name with a compared date suffix."""
    base_name = original_name.rsplit(".", 1)[0] if "." in original_name else original_name
    return f"{base_name}_compared_{date.today().isoformat()}.xlsx"
