from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from backend.excel_comparator.utils.helpers import build_composite_key

@dataclass
class MappedField:
    source_col: str
    target_col: str


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

    def validate(self, source_df: pd.DataFrame, target_df: pd.DataFrame) -> None:
        """Raises ValueError with clear message if any column is missing."""
        if not self.key_fields:
            raise ValueError("At least one key field mapping is required.")

        source_cols = set(source_df.columns)
        target_cols = set(target_df.columns)

        for field in self.key_fields:
            if field.source_col not in source_cols:
                raise ValueError(f"Mapped source key column missing: '{field.source_col}'.")
            if field.target_col not in target_cols:
                raise ValueError(f"Mapped target key column missing: '{field.target_col}'.")

        for field in self.compare_fields:
            if field.source_col not in source_cols:
                raise ValueError(f"Mapped source compare column missing: '{field.source_col}'.")
            if field.target_col not in target_cols:
                raise ValueError(f"Mapped target compare column missing: '{field.target_col}'.")

    def normalise_key(self, row: pd.Series, cols: list[str]) -> str:
        """Build composite key string from row values. Normalise per options."""
        return build_composite_key(row=row, cols=cols, options=self.options)
