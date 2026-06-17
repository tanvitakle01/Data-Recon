from __future__ import annotations

from typing import Any

import pandas as pd

from backend.excel_comparator.core.mapper import ColumnMapper
from backend.excel_comparator.utils.helpers import build_summary, compute_delta, normalise_value


class ExcelComparator:
    def __init__(self, source_df: pd.DataFrame, target_df: pd.DataFrame, mapper: ColumnMapper):
        self.source_df = source_df.copy()
        self.target_df = target_df.copy()
        self.mapper = mapper

        self._source_key_col = "__source_key__"
        self._target_key_col = "__target_key__"
        self._matched_mask = pd.Series(False, index=self.target_df.index)

    def _build_keys(self) -> None:
        self.source_df[self._source_key_col] = self.source_df.apply(
            lambda row: self.mapper.normalise_key(row, self.mapper.source_key_cols), axis=1
        )
        self.target_df[self._target_key_col] = self.target_df.apply(
            lambda row: self.mapper.normalise_key(row, self.mapper.target_key_cols), axis=1
        )

    def _ensure_remarks_col(self) -> None:
        if "Remarks" in self.target_df.columns:
            self.target_df = self.target_df.drop(columns=["Remarks"])
        self.target_df["Remarks"] = ""

    def _format_source_key(self, source_row: pd.Series) -> str:
        key_parts = [
            normalise_value(
                source_row.get(col),
                case_insensitive=self.mapper.options.get("case_insensitive", True),
                trim=self.mapper.options.get("trim_whitespace", True),
            )
            for col in self.mapper.source_key_cols
        ]
        return "-".join(key_parts)

    def scenario_1_matches(self) -> None:
        """Mark target rows whose key exists in source."""
        source_keys = set(self.source_df[self._source_key_col])
        self._matched_mask = self.target_df[self._target_key_col].isin(source_keys)
        self.target_df.loc[self._matched_mask, "Remarks"] = "✅ MATCH | Key found in Source"

    def scenario_2_qty_mismatch(self) -> None:
        """Compare mapped fields for matched keys and override Remarks for mismatches."""
        if not self.mapper.compare_fields:
            return

        source_lookup = self.source_df.drop_duplicates(subset=[self._source_key_col], keep="first").set_index(self._source_key_col)

        for idx, target_row in self.target_df[self._matched_mask].iterrows():
            key = target_row[self._target_key_col]
            if key not in source_lookup.index:
                continue

            source_row = source_lookup.loc[key]
            mismatch_message = ""

            for field in self.mapper.compare_fields:
                src_val = source_row.get(field.source_col)
                tgt_val = target_row.get(field.target_col)

                src_num = pd.to_numeric(src_val, errors="coerce")
                tgt_num = pd.to_numeric(tgt_val, errors="coerce")

                if not pd.isna(src_num) and not pd.isna(tgt_num):
                    if src_num != tgt_num:
                        delta = compute_delta(src_val, tgt_val)
                        mismatch_message = (
                            f"⚠️ QTY MISMATCH | Expected: {src_val} | Actual: {tgt_val} | Delta: {delta}"
                        )
                        break
                else:
                    norm_src = normalise_value(
                        src_val,
                        case_insensitive=self.mapper.options.get("case_insensitive", True),
                        trim=self.mapper.options.get("trim_whitespace", True),
                    )
                    norm_tgt = normalise_value(
                        tgt_val,
                        case_insensitive=self.mapper.options.get("case_insensitive", True),
                        trim=self.mapper.options.get("trim_whitespace", True),
                    )
                    if norm_src != norm_tgt:
                        mismatch_message = (
                            f"⚠️ QTY MISMATCH | Expected: {src_val} | Actual: {tgt_val} | Delta: N/A"
                        )
                        break

            if mismatch_message:
                self.target_df.at[idx, "Remarks"] = mismatch_message

    def scenario_3_missing_in_target(self) -> None:
        """Append source keys missing in target as new target-format rows."""
        source_keys = set(self.source_df[self._source_key_col])
        target_keys = set(self.target_df[self._target_key_col])
        missing_keys = source_keys - target_keys
        if not missing_keys:
            return

        target_columns = [col for col in self.target_df.columns if col not in {self._target_key_col}]
        appended_rows: list[dict[str, Any]] = []

        source_missing_rows = self.source_df[self.source_df[self._source_key_col].isin(missing_keys)]

        for _, src_row in source_missing_rows.iterrows():
            new_row = {col: pd.NA for col in target_columns}

            for field in self.mapper.key_fields:
                new_row[field.target_col] = src_row.get(field.source_col)

            for field in self.mapper.compare_fields:
                new_row[field.target_col] = src_row.get(field.source_col)

            key_text = self._format_source_key(src_row)
            new_row["Remarks"] = f"❌ MISSING IN TARGET | Key: {key_text} not found in IBP"
            appended_rows.append(new_row)

        if appended_rows:
            append_df = pd.DataFrame(appended_rows)
            append_df[self._target_key_col] = append_df.apply(
                lambda row: self.mapper.normalise_key(row, self.mapper.target_key_cols), axis=1
            )
            self.target_df = pd.concat([self.target_df, append_df], ignore_index=True)

    def bonus_extra_in_target(self) -> None:
        """Mark target rows whose key does not exist in source."""
        source_keys = set(self.source_df[self._source_key_col])
        extra_mask = ~self.target_df[self._target_key_col].isin(source_keys)

        unmarked_extras = extra_mask & self.target_df["Remarks"].fillna("").eq("")
        for idx, row in self.target_df[unmarked_extras].iterrows():
            key_text = str(row.get(self._target_key_col, "")).replace("|", "-")
            self.target_df.at[idx, "Remarks"] = f"🔶 EXTRA IN TARGET | Key: {key_text} not in Source"

    def run(self, scenarios: list[int]) -> tuple[pd.DataFrame, dict[str, int]]:
        """Run selected scenarios and return annotated target DataFrame and summary."""
        self._build_keys()
        self._ensure_remarks_col()

        ordered = [1, 2, 3, 4]
        selected = [scenario for scenario in ordered if scenario in scenarios]

        if 1 in selected:
            self.scenario_1_matches()
        if 2 in selected:
            self.scenario_2_qty_mismatch()
        if 3 in selected:
            self.scenario_3_missing_in_target()
        if 4 in selected:
            self.bonus_extra_in_target()

        result_df = self.target_df.drop(columns=[self._target_key_col], errors="ignore")
        summary = build_summary(result_df)
        return result_df, summary
