"""Deterministic mapping-sheet parser: Excel/CSV worksheet -> structured JSON.

Responsibility boundary (by design):
    * Excel -> structured JSON only. Lossless: every column, row value and
      preamble/metadata cell is preserved exactly as it appears in the sheet.
    * NO transformation contracts, operations, or executable rules are
      generated here — that is the contract compiler's job.
    * NO LLM interpretation. Parsing is deterministic and auditable; the same
      workbook always produces the same payload.

Supports both simple mapping templates (``Source_Field`` / ``Target_Field`` /
``Transformation_Rule``) and enterprise SAP/IBP mapping workbooks whose
mapping information is embedded in columns such as ``Target Fields``,
``Technical Field``, ``Source Table/Field``, ``Description``,
``Transformation``, ``Join Condition`` and ``Filter`` — without assuming any
fixed column names. Nothing is required to be present: roles that cannot be
detected simply yield empty candidate/note lists while the raw rows remain
fully available for the compiler.

The returned payload is suitable as the ``mapping_sheet`` field of
``POST /api/recon/contracts/compile``.
"""

from __future__ import annotations

import datetime as _dt
import math
import re
from io import BytesIO
from typing import Any

import numpy as np
import pandas as pd

# Roles a mapping-sheet column can play. Hints are matched against normalised
# headers (lowercase, alphanumerics only): exact match first, then substring
# in _ROLE_PRIORITY order, so specific roles ("join_condition") win over broad
# ones ("target") and "Source Field Description" classifies as description,
# not source.
_ROLE_HINTS: dict[str, tuple[str, ...]] = {
    "source": (
        "sourcetablefield", "sourcefield", "sourcecolumn", "sourcecol",
        "sourcetable", "source", "fromfield", "from", "s4field", "s4hana",
        "eccfield", "ecc", "senderfield", "sender",
    ),
    "target": (
        "targetfield", "targetcolumn", "targetcol", "target", "tofield", "to",
        "ibpfield", "ibpattribute", "ibpkeyfigure", "ibp",
        "receiverfield", "receiver",
    ),
    "technical": (
        "technicalfield", "technicalname", "technicalcolumn", "technical",
        "abapfield", "fieldname",
    ),
    "description": (
        "fielddescription", "businessdescription", "description", "desc",
        "businessmeaning", "longtext", "remarks", "remark", "comments",
        "comment", "notes", "note",
    ),
    "transformation": (
        "transformationrule", "transformationlogic", "transformation",
        "transform", "mappingrule", "mappinglogic", "derivationrule",
        "derivation", "conversionrule", "conversion", "businessrule", "rules",
        "rule", "logic", "formula", "calculation",
    ),
    "join_condition": (
        "joinconditions", "joincondition", "joincriteria", "joinlogic",
        "join", "lookupcondition", "lookup",
    ),
    "filter": (
        "filterconditions", "filtercondition", "filtercriteria", "filters",
        "filter", "selectioncondition", "selection", "wherecondition",
        "whereclause", "where",
    ),
}

# Substring-match priority: most specific first, description before
# source/target so "<side> description" columns land on description.
_ROLE_PRIORITY = (
    "join_condition", "filter", "transformation", "technical",
    "description", "source", "target",
)

# Short hints ("to", "from", "join", "rule", …) only ever match a header
# exactly; using them as substrings would misclassify headers like "Total"
# or free text like "cast to string".
_MIN_SUBSTRING_HINT_LEN = 5

# Generic header vocabulary — used only to score header-row detection, never
# to classify a column into a role.
_GENERIC_HEADER_TOKENS = (
    "field", "column", "table", "mapping", "attribute", "keyfigure", "key",
)


def _norm(text: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def _classify(header: str) -> str | None:
    norm = _norm(header)
    if not norm:
        return None
    for role, hints in _ROLE_HINTS.items():
        if norm in hints:
            return role
    for role in _ROLE_PRIORITY:
        for hint in _ROLE_HINTS[role]:
            if len(hint) >= _MIN_SUBSTRING_HINT_LEN and hint in norm:
                return role
    return None


def _json_safe(value: Any) -> Any:
    """Convert one cell to a JSON-serialisable value without losing content."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, (int, float, str)):
        return value
    if isinstance(value, (pd.Timestamp, _dt.datetime, _dt.date, _dt.time)):
        return value.isoformat()
    return str(value)


def _load_grid(
    content: bytes, filename: str, sheet_name: str | None
) -> tuple[list[list[Any]], str, list[str]]:
    """Read the raw worksheet with NO header assumption -> (grid, sheet, sheets)."""
    if filename.lower().endswith(".csv"):
        df = pd.read_csv(BytesIO(content), header=None, dtype=object)
        active = sheet_name or filename
        sheets = [active]
    else:
        try:
            excel_file = pd.ExcelFile(BytesIO(content))
        except Exception as exc:
            raise ValueError(
                "Unable to read the mapping workbook. Please verify the file format."
            ) from exc
        sheets = list(excel_file.sheet_names or [])
        if not sheets:
            raise ValueError("No worksheets found in the mapping workbook.")
        active = sheet_name or sheets[0]
        if active not in sheets:
            raise ValueError(f"Selected sheet '{active}' does not exist.")
        df = pd.read_excel(excel_file, sheet_name=active, header=None, dtype=object)

    grid = [[_json_safe(cell) for cell in row] for row in df.itertuples(index=False)]
    return grid, active, sheets


def _detect_header_row(grid: list[list[Any]]) -> int:
    """Pick the header row deterministically.

    Enterprise workbooks often carry banner/title rows above the real header.
    Score each of the first rows by how many cells classify into a known role
    (heavily weighted) plus how many distinct text cells it has; earliest row
    wins ties. Falls back to the first row with at least two filled cells.
    """
    best_idx, best_score = 0, -1
    fallback_idx: int | None = None
    for idx, row in enumerate(grid[: min(len(grid), 25)]):
        cells = [c for c in row if c not in (None, "")]
        if len(cells) < 2:
            continue
        if fallback_idx is None:
            fallback_idx = idx
        texts = [c for c in cells if isinstance(c, str)]
        role_hits = sum(1 for c in texts if _classify(c) is not None)
        generic_hits = sum(
            1 for c in texts if any(tok in _norm(c) for tok in _GENERIC_HEADER_TOKENS)
        )
        score = role_hits * 10 + generic_hits * 2 + len({c.strip() for c in texts})
        if score > best_score:
            best_idx, best_score = idx, score
    if best_score <= 0:
        return fallback_idx if fallback_idx is not None else 0
    return best_idx


def _build_headers(header_row: list[Any]) -> list[str]:
    """Stringify the header row; name blanks positionally and dedupe repeats."""
    headers: list[str] = []
    seen: dict[str, int] = {}
    for pos, cell in enumerate(header_row):
        name = str(cell).strip() if cell not in (None, "") else f"Column_{pos + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        seen.setdefault(name, 1)
        headers.append(name)
    return headers


def _first_nonempty(record: dict[str, Any], columns: list[str]) -> str | None:
    for col in columns:
        value = record.get(col)
        if value not in (None, ""):
            return str(value).strip()
    return None


def parse_mapping_sheet(
    content: bytes, *, filename: str, sheet_name: str | None = None
) -> dict[str, Any]:
    """Parse one worksheet of a mapping template/workbook into structured JSON.

    Returns a lossless payload::

        {
          "sheet_name": ..., "sheets": [...], "headers": [...],
          "rows": [...],                # every column and value preserved
          "row_count": ...,
          "detected_columns": {role: [headers]},
          "mapping_candidates": [...],  # inferred source/target pairs, if any
          "transformation_notes": [...],
          "join_conditions": [...],
          "filters": [...],
          "metadata": {header_row_index, preamble_rows, empty_row_indices, ...},
        }

    ``mapping_candidates`` and the note lists are *inferences over headers
    only* — the row content itself is never rewritten, and no contract,
    operation, or rule is produced here.
    """
    grid, active_sheet, sheets = _load_grid(content, filename, sheet_name)
    if not grid:
        raise ValueError(f"Sheet '{active_sheet}' is empty.")

    header_idx = _detect_header_row(grid)
    headers = _build_headers(grid[header_idx])
    preamble_rows = [row for row in grid[:header_idx]]

    rows: list[dict[str, Any]] = []
    empty_row_indices: list[int] = []
    for offset, raw in enumerate(grid[header_idx + 1 :]):
        if all(cell in (None, "") for cell in raw):
            empty_row_indices.append(header_idx + 1 + offset)
            continue
        rows.append(dict(zip(headers, raw)))

    # Header-role detection (each header lands on at most one role).
    detected: dict[str, list[str]] = {role: [] for role in _ROLE_HINTS}
    for header in headers:
        role = _classify(header)
        if role is not None:
            detected[role].append(header)

    # Inferred mapping candidates: one per row that names a source, target or
    # technical field. Values are trimmed strings; the untouched originals
    # remain in ``rows``.
    mapping_candidates: list[dict[str, Any]] = []
    for idx, record in enumerate(rows):
        candidate = {
            "row_index": idx,
            "source_field": _first_nonempty(record, detected["source"]),
            "target_field": _first_nonempty(record, detected["target"]),
            "technical_field": _first_nonempty(record, detected["technical"]),
            "description": _first_nonempty(record, detected["description"]),
            "transformation": _first_nonempty(record, detected["transformation"]),
            "join_condition": _first_nonempty(record, detected["join_condition"]),
            "filter": _first_nonempty(record, detected["filter"]),
        }
        if candidate["source_field"] or candidate["target_field"] or candidate["technical_field"]:
            mapping_candidates.append(candidate)

    def _collect_notes(role: str) -> list[dict[str, Any]]:
        notes: list[dict[str, Any]] = []
        for column in detected[role]:
            for idx, record in enumerate(rows):
                value = record.get(column)
                if value in (None, ""):
                    continue
                notes.append(
                    {
                        "row_index": idx,
                        "column": column,
                        "text": str(value).strip(),
                        "source_field": _first_nonempty(record, detected["source"]),
                        "target_field": _first_nonempty(record, detected["target"]),
                    }
                )
        return notes

    return {
        "sheet_name": active_sheet,
        "sheets": sheets,
        "headers": headers,
        "rows": rows,
        "row_count": len(rows),
        "detected_columns": detected,
        "mapping_candidates": mapping_candidates,
        "transformation_notes": _collect_notes("transformation"),
        "join_conditions": _collect_notes("join_condition"),
        "filters": _collect_notes("filter"),
        "metadata": {
            "header_row_index": header_idx,
            "preamble_rows": preamble_rows,
            "empty_row_indices": empty_row_indices,
            "column_count": len(headers),
        },
    }
