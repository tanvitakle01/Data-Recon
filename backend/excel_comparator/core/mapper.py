from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from backend.excel_comparator.utils.helpers import build_composite_key

logger = logging.getLogger(__name__)


@dataclass
class MappedField:
    source_col: str
    target_col: str


def _normalise_col(name: Any) -> str:
    """Normalise a column name for tolerant matching (trim + casefold)."""
    return str(name).strip().casefold()


def _build_lookup(columns: list[str]) -> dict[str, str]:
    """Map normalised column name -> actual column name.

    On a normalised collision (two columns that differ only by case/whitespace)
    the first occurrence wins; the clash is logged so it can be spotted.
    """
    lookup: dict[str, str] = {}
    for col in columns:
        key = _normalise_col(col)
        if key in lookup and lookup[key] != col:
            logger.warning(
                "Ambiguous columns after normalisation: '%s' and '%s' both map to '%s'; "
                "using '%s'.",
                lookup[key], col, key, lookup[key],
            )
            continue
        lookup[key] = col
    return lookup


class ColumnMapper:
    def __init__(self, mapping: dict[str, Any]):
        self.mapping = mapping or {}

        self.key_fields = [
            MappedField(source_col=item["source_col"], target_col=item["target_col"])
            for item in self.mapping.get("key_fields", [])
            if item.get("source_col") and item.get("target_col")
        ]
        self.compare_fields = [
            MappedField(source_col=item["source_col"], target_col=item["target_col"])
            for item in self.mapping.get("compare_fields", [])
            if item.get("source_col") and item.get("target_col")
        ]
        self.options = {
            "case_insensitive": bool(self.mapping.get("options", {}).get("case_insensitive", True)),
            "trim_whitespace": bool(self.mapping.get("options", {}).get("trim_whitespace", True)),
        }

    @property
    def source_key_cols(self) -> list[str]:
        return [field.source_col for field in self.key_fields]

    @property
    def target_key_cols(self) -> list[str]:
        return [field.target_col for field in self.key_fields]

    def _resolve(
        self,
        requested: str,
        columns: list[str],
        lookup: dict[str, str],
        *,
        side: str,
        role: str,
    ) -> str:
        """Resolve a mapped column name to an actual DataFrame column.

        Matching is tolerant of leading/trailing whitespace and case. If the
        column cannot be resolved, raise a clear error listing the available
        columns so the mismatch is obvious.
        """
        requested_str = str(requested)

        # 1. Exact match (fast path).
        if requested_str in columns:
            return requested_str

        # 2. Whitespace-tolerant then case-insensitive match.
        actual = lookup.get(_normalise_col(requested_str))
        if actual is not None:
            logger.info(
                "Mapping resolved %s %s column '%s' -> actual column '%s' "
                "(whitespace/case-insensitive match).",
                side, role, requested_str, actual,
            )
            return actual

        # 3. No match — fail loudly with the available columns.
        logger.error(
            "Mapping validation failed: %s %s column '%s' not found. "
            "Available %s columns: %s",
            side, role, requested_str, side, columns,
        )
        raise ValueError(
            f"Mapped {side} {role} column '{requested_str}' was not found. "
            f"Available {side} columns: {columns}"
        )

    def validate(self, source_df: pd.DataFrame, target_df: pd.DataFrame) -> None:
        """Resolve every mapped column against the actual data and validate it.

        Resolved (whitespace/case-corrected) column names are written back onto
        the mapped fields so downstream key-building and comparison use the real
        DataFrame column names. Raises ValueError with a clear, column-listing
        message if any mapped column is missing.
        """
        if not self.key_fields:
            raise ValueError("At least one key field mapping is required.")

        source_cols = [str(c) for c in source_df.columns]
        target_cols = [str(c) for c in target_df.columns]

        logger.info(
            "Validating mapping | source columns=%s | target columns=%s",
            source_cols, target_cols,
        )

        src_lookup = _build_lookup(source_cols)
        tgt_lookup = _build_lookup(target_cols)

        for field in self.key_fields:
            field.source_col = self._resolve(
                field.source_col, source_cols, src_lookup, side="source", role="key"
            )
            field.target_col = self._resolve(
                field.target_col, target_cols, tgt_lookup, side="target", role="key"
            )

        for field in self.compare_fields:
            field.source_col = self._resolve(
                field.source_col, source_cols, src_lookup, side="source", role="compare"
            )
            field.target_col = self._resolve(
                field.target_col, target_cols, tgt_lookup, side="target", role="compare"
            )

        logger.info(
            "Mapping validated | key_fields=%s | compare_fields=%s",
            [(f.source_col, f.target_col) for f in self.key_fields],
            [(f.source_col, f.target_col) for f in self.compare_fields],
        )

    def normalise_key(self, row: pd.Series, cols: list[str]) -> str:
        """Build composite key string from row values. Normalise per options."""
        return build_composite_key(row=row, cols=cols, options=self.options)
