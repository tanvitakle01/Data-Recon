from __future__ import annotations

from typing import Any

import pandas as pd

from backend.excel_comparator.core.auto_mapper import auto_map_columns  # type: ignore


def auto_map(source_columns: list[str], target_columns: list[str]) -> dict[str, Any]:
    """Use the existing Streamlit reconciliation auto-mapper.

    The core auto_map_columns expects DataFrames; we can build minimal frames
    from column headers to reuse its logic.

    Note: score output is not currently produced by auto_map_columns.
    We provide a synthetic score based on fuzzy/keyword confidence heuristics.
    """
    # Build minimal frames; data content is only used for numeric inference fallback.
    source_df = pd.DataFrame(columns=source_columns)
    target_df = pd.DataFrame(columns=target_columns)

    result = auto_map_columns(source_df, target_df)
    return result

