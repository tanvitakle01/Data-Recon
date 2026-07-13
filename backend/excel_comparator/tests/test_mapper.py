from __future__ import annotations

import pandas as pd
import pytest

from backend.excel_comparator.core.comparator import ExcelComparator
from backend.excel_comparator.core.mapper import ColumnMapper


def _mapping(source_col: str = "Plant", target_col: str = "Plant"):
    return {
        "key_fields": [{"source_col": source_col, "target_col": target_col}],
        "compare_fields": [],
        "options": {"case_insensitive": True, "trim_whitespace": True},
    }


def test_validate_exact_match():
    mapper = ColumnMapper(_mapping())
    src = pd.DataFrame({"Plant": ["1000"]})
    tgt = pd.DataFrame({"Plant": ["1000"]})
    mapper.validate(src, tgt)  # no raise
    assert mapper.key_fields[0].source_col == "Plant"


def test_validate_resolves_trailing_space():
    mapper = ColumnMapper(_mapping())
    src = pd.DataFrame({"Plant ": ["1000"]})  # trailing space in actual column
    tgt = pd.DataFrame({" Plant": ["1000"]})  # leading space in actual column
    mapper.validate(src, tgt)
    # Mapped names rewritten to the real DataFrame column names.
    assert mapper.key_fields[0].source_col == "Plant "
    assert mapper.key_fields[0].target_col == " Plant"


def test_validate_resolves_case_insensitive():
    mapper = ColumnMapper(_mapping())
    src = pd.DataFrame({"plant": ["1000"]})
    tgt = pd.DataFrame({"PLANT": ["1000"]})
    mapper.validate(src, tgt)
    assert mapper.key_fields[0].source_col == "plant"
    assert mapper.key_fields[0].target_col == "PLANT"


def test_validate_missing_column_lists_available_columns():
    mapper = ColumnMapper(_mapping())
    src = pd.DataFrame({"Plnt": ["1000"], "Material": ["M1"]})  # no "Plant"
    tgt = pd.DataFrame({"Plant": ["1000"]})
    with pytest.raises(ValueError) as exc:
        mapper.validate(src, tgt)
    msg = str(exc.value)
    assert "was not found" in msg
    assert "Available source columns" in msg
    assert "Plnt" in msg and "Material" in msg


def test_validate_requires_key_field():
    mapper = ColumnMapper({"key_fields": [], "compare_fields": []})
    with pytest.raises(ValueError):
        mapper.validate(pd.DataFrame({"a": [1]}), pd.DataFrame({"a": [1]}))


def test_comparator_matches_despite_space_and_case_difference():
    # Mapping says "Plant"/"Plant" but the real columns differ by space/case.
    mapper = ColumnMapper(_mapping())
    src = pd.DataFrame({"Plant ": ["1000", "2000"]})
    tgt = pd.DataFrame({"PLANT": ["1000", "3000"]})
    mapper.validate(src, tgt)

    result_df, _ = ExcelComparator(src, tgt, mapper).run([1, 2, 3, 4])
    remarks = result_df["Remarks"].tolist()
    # 1000 exists on both sides -> a MATCH remark is produced.
    assert any(r.startswith("✅") for r in remarks)
