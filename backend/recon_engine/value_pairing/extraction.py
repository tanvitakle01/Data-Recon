"""Deterministic distinct-value extraction — pipeline step 1.

Factors out the ``.dropna().astype(str)...value_counts()`` logic the retired
per-field matchers (``matching.product``/``matching.location``) each inlined
separately. Pure function of the real column values, no I/O.
"""

from __future__ import annotations

import pandas as pd


def distinct_values(series: pd.Series) -> dict[str, int]:
    """Every distinct non-blank value in ``series`` -> its row count.

    "Blank" means null or an empty/whitespace-only string after stringifying —
    a blank value can never form a business key, so it is dropped here rather
    than surfacing as a spurious "unpaired" entry downstream.
    """
    values = series.dropna().astype(str)
    values = values[values.str.strip() != ""]
    counts = values.value_counts()
    return {str(value): int(count) for value, count in counts.items()}
