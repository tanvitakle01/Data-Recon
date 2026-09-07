"""Workbook interface index: discover which INTERFACES a mapping workbook holds.

A mapping workbook is not one dataset — it is a collection of interfaces, one
worksheet each, indexed by a dedicated "Interfaces" sheet. This module reads
only that index and resolves each listed interface to its own worksheet, so
Step 1 can offer the interface list as the Dataset Type choice and then hand
the contract/connector interpretation exactly ONE sheet.

Responsibility boundary (mirrors ``mapping_sheet_parser``):
    * Sheet-name and index-column discovery only. Nothing here reads an
      interface's field table — that stays ``parse_mapping_sheet``'s job,
      called later with the resolved ``sheet_name``.
    * Deterministic and auditable. No LLM, no fuzzy scoring: record -> sheet
      resolution is a fixed two-tier match (normalised-exact, then UNIQUE
      substring) and anything that doesn't land on exactly one sheet is
      reported broken rather than guessed at.

A SINGLE-SHEET upload is a first-class case, not a degraded one: the user
uploaded one interface's sheet rather than the whole project workbook, so that
sheet IS the dataset. It is short-circuited before any index detection —
one interface, no choice to make, no warning — and handed straight to the same
interpretation step (``parse_mapping_sheet`` -> ``identify_systems``) that an
indexed workbook's chosen sheet gets. Nothing about the AI step changes; only
how the sheet reaches it.

When a MULTI-sheet workbook has no usable index — no "Interfaces" sheet, no
``IBP Record`` column, or an index that lists nothing — the workbook's own
worksheet names ARE the interface list, and every one of them is offered, with
a warning saying why. A workbook is never reduced to just its first sheet: that
would hide real interfaces behind an index the workbook happens not to have.
"""

from __future__ import annotations

import re
from io import BytesIO
from typing import Any

import pandas as pd

# The index sheet's name, matched against the sheet name with ALL whitespace
# removed and lowercased — so "Interfaces", "Interface", "Interfaces List",
# "interface list" and "InterfacesList" all match, and nothing else does.
_INDEX_SHEET_RE = re.compile(r"^interfaces?(list)?$")

# The index column holding each interface's name. Whitespace-tolerant so
# "IBP Record", "IBP Data Record" and "IBPDataRecord" all match.
_RECORD_COLUMN_RE = re.compile(r"ibp\s*(data\s*)?record", re.IGNORECASE)

# Optional column naming each interface's own worksheet. When present it is
# authoritative and no name matching happens at all.
_SHEET_COLUMN_RE = re.compile(r"^(sheet|tab)(\s*name)?$", re.IGNORECASE)

# How far down the index sheet to look for its header row. Enterprise
# workbooks put a banner/title block above it, never dozens of rows.
_MAX_HEADER_SCAN_ROWS = 30

# Default worksheet names carrying no information ("Sheet1", "Tab 2", …).
# Only consulted for a single-sheet upload, to decide whether the sheet can
# name the dataset or the FILE has to.
_GENERIC_SHEET_RE = re.compile(r"^(sheet|tab|worksheet|page|data)\d*$")

# Workbook/CSV extensions stripped when the filename has to name the dataset.
_EXTENSION_RE = re.compile(r"\.(xlsx|xlsm|xlsb|xls|csv)$", re.IGNORECASE)


def _norm(text: Any) -> str:
    """Lowercase, alphanumerics only — the comparison form for names."""
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def _cell(value: Any) -> str:
    """One cell as a trimmed string; empty for blanks/NaN."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def find_index_sheet(sheet_names: list[str]) -> str | None:
    """The workbook's interface-index sheet, or None if it has none."""
    for name in sheet_names:
        if _INDEX_SHEET_RE.match(re.sub(r"\s+", "", str(name)).lower()):
            return name
    return None


def _find_header(grid: list[list[Any]]) -> tuple[int, int, int | None] | None:
    """Locate the index sheet's header row.

    The header row is simply the first row carrying an ``IBP (Data) Record``
    cell — no scoring needed, since that column is what defines the index.
    Returns ``(row_index, record_col, sheet_col | None)``.
    """
    for row_idx, row in enumerate(grid[:_MAX_HEADER_SCAN_ROWS]):
        record_col = None
        sheet_col = None
        for col_idx, raw in enumerate(row):
            text = _cell(raw)
            if not text:
                continue
            if record_col is None and _RECORD_COLUMN_RE.search(text):
                record_col = col_idx
            elif sheet_col is None and _SHEET_COLUMN_RE.match(text):
                sheet_col = col_idx
        if record_col is not None:
            return row_idx, record_col, sheet_col
    return None


def _resolve_sheet(record: str, candidates: list[str]) -> tuple[str | None, str, list[str]]:
    """Match one interface name to one worksheet.

    Two tiers, both requiring a UNIQUE winner:
        1. normalised-exact  — "Available Stock" -> "AvailableStock"
        2. unique substring  — "Product Master" -> "Product Master Data"

    Returns ``(sheet | None, match_kind, competing_candidates)``. A tier that
    matches two or more sheets does NOT fall through to the next tier: the
    record is genuinely ambiguous and is reported as such, never guessed.
    """
    target = _norm(record)
    if not target:
        return None, "none", []

    exact = [s for s in candidates if _norm(s) == target]
    if len(exact) == 1:
        return exact[0], "exact", []
    if len(exact) > 1:
        return None, "ambiguous", exact

    # `_norm(s)` must be non-empty: a divider sheet ("---", ">>", "( )") all of
    # whose characters are punctuation normalises to "", and "" is a substring
    # of every record — it would match ALL of them, turning single matches into
    # false "ambiguous" and resolving otherwise-unmatched records to junk.
    partial = [
        s for s in candidates if _norm(s) and (target in _norm(s) or _norm(s) in target)
    ]
    if len(partial) == 1:
        return partial[0], "substring", []
    if len(partial) > 1:
        return None, "ambiguous", partial

    return None, "none", []


def _interface_ids(records: list[str]) -> list[str]:
    """Stable slug per record, matching the historical comparison-type ids.

    ``"Sales Order History" -> "salesorderhistory"``, so an interface-driven
    run keys the attribute/value libraries exactly as the old hardcoded
    dataset types did. Records are unique by construction, but two distinct
    records can still slug identically ("A-B" / "A B") — suffix those so an id
    always identifies one interface.

    The suffix search keeps going until the slug is genuinely unused: a bare
    ``f"{slug}2"`` can itself collide with a record that already slugs to it
    (``["X", "X2", "X."]``), and the UI resolves a selection by id alone, so a
    duplicate would silently parse the wrong worksheet.
    """
    ids: list[str] = []
    used: set[str] = set()
    for index, record in enumerate(records):
        base = _norm(record) or f"interface{index + 1}"
        slug, suffix = base, 1
        while slug in used:
            suffix += 1
            slug = f"{base}{suffix}"
        used.add(slug)
        ids.append(slug)
    return ids


def _file_stem(filename: str) -> str:
    """The upload's own name, without directory parts or extension."""
    base = re.split(r"[\\/]", str(filename).strip())[-1]
    return _EXTENSION_RE.sub("", base).strip()


def _dataset_name(filename: str, sheet: str) -> str:
    """What to call a single-sheet upload's one dataset.

    The worksheet names it when it says anything ("Sales Order History"). The
    FILE names it instead when the worksheet can't: a default Excel name
    ("Sheet1", "Tab 2"), or a CSV, whose "sheet" is just the filename repeated
    and would otherwise label the dataset "mapping.csv". Either way that is
    where a user exporting one interface put the interface's name.
    """
    name = _cell(sheet)
    generic = (
        not name
        or _norm(name) == _norm(filename)
        or bool(_GENERIC_SHEET_RE.match(_norm(name)))
    )
    if not generic:
        return name
    return _file_stem(filename) or name or "Mapping sheet"


def _single_sheet_payload(filename: str, sheet: str) -> dict[str, Any]:
    """One sheet uploaded => that sheet IS the dataset.

    Deliberately warning-free: this is not an index that failed to be found,
    it is an upload that never had one to find. ``single_sheet`` lets the
    wizard say so instead of reporting a fallback, and ``match="single"``
    distinguishes it from the multi-sheet ``match="sheet"`` fallback.
    """
    record = _dataset_name(filename, sheet)
    return {
        "sheets": [sheet],
        "index_sheet": None,
        "record_column": None,
        "sheet_column": None,
        "interfaces": [
            {
                "id": _interface_ids([record])[0],
                "record": record,
                "sheet": sheet,
                "status": "ok",
                "match": "single",
                "candidates": [],
            }
        ],
        "indexed": False,
        "single_sheet": True,
        "warnings": [],
    }


def _sheet_fallback_payload(
    filename: str,
    sheets: list[str],
    reason: str,
    *,
    exclude: str | None = None,
) -> dict[str, Any]:
    """No usable index: offer EVERY worksheet as an interface.

    A workbook whose index sheet is missing or unreadable still names its
    interfaces — one per worksheet ("Sales Order History", "Product Master",
    …). Listing all of them keeps the workbook fully reachable, where falling
    back to just the first sheet would hide the rest behind an index the
    workbook happens not to have.

    ``exclude`` drops a sheet already positively identified as the index
    itself, so a present-but-unreadable index sheet isn't offered as data.
    Nothing else is filtered: guessing which worksheets are "not really
    interfaces" would silently hide real ones.

    Only ever reached for a MULTI-sheet workbook — a one-sheet upload is
    short-circuited by :func:`_single_sheet_payload` before any index
    detection runs, so it never appears here as a "fallback".
    """
    candidates = [s for s in sheets if s != exclude] or sheets or [filename]
    return {
        "sheets": sheets,
        "index_sheet": None,
        "record_column": None,
        "sheet_column": None,
        "interfaces": [
            {
                "id": slug,
                "record": name,
                "sheet": name if sheets else None,
                "status": "ok",
                "match": "sheet",
                "candidates": [],
            }
            for name, slug in zip(candidates, _interface_ids(candidates))
        ],
        "indexed": False,
        "single_sheet": False,
        "warnings": [
            f"{reason} — listing "
            + (
                "the workbook's 1 remaining worksheet"
                if len(candidates) == 1
                else f"all {len(candidates)} worksheets"
            )
            + " as interfaces."
        ],
    }


def read_interface_index(content: bytes, *, filename: str) -> dict[str, Any]:
    """Read a mapping workbook's interface index.

    Returns::

        {
          "sheets": [...],               # every worksheet in the workbook
          "index_sheet": "Interfaces",   # None when the workbook has no index
          "record_column": "IBP Data Record",
          "sheet_column": "Sheet" | None,
          "interfaces": [
            {"id", "record", "sheet", "status", "match", "candidates"}
          ],
          "indexed": True,               # False = worksheet-name fallback
          "single_sheet": False,         # True = one-sheet upload, see below
          "warnings": [...],
        }

    ``status`` is ``"ok"`` (runnable — ``sheet`` names its worksheet) or
    ``"broken"``. A broken interface carries ``match="none"`` (no worksheet
    matches its name) or ``match="ambiguous"`` (several do, listed in
    ``candidates``); either way it is reported, never resolved by guesswork,
    and never crashes the read.

    With ``indexed=False`` every interface came from a worksheet NAME rather
    than an index row (``match="sheet"``), so all of them are ``"ok"`` by
    construction — the sheet is where the name came from.

    With ``single_sheet=True`` the upload held exactly one sheet (or was a
    CSV): that sheet is the dataset, it is the sole interface (``match=
    "single"``), and there are no warnings — the absence of an index is the
    expected shape of this upload, not a problem with it.
    """
    if filename.lower().endswith(".csv"):
        # A CSV is one sheet by definition — the same single-sheet case.
        return _single_sheet_payload(filename, filename)

    try:
        excel_file = pd.ExcelFile(BytesIO(content))
    except Exception as exc:
        raise ValueError(
            "Unable to read the mapping workbook. Please verify the file format."
        ) from exc

    sheets = [str(name) for name in (excel_file.sheet_names or [])]
    if not sheets:
        raise ValueError("No worksheets found in the mapping workbook.")

    # One sheet => that sheet is the dataset. Checked BEFORE index detection,
    # which also makes the degenerate "the only sheet is called Interfaces"
    # workbook work: index detection would claim it, then exclude it from its
    # own candidate list and resolve every record to nothing.
    if len(sheets) == 1:
        return _single_sheet_payload(filename, sheets[0])

    index_sheet = find_index_sheet(sheets)
    if index_sheet is None:
        return _sheet_fallback_payload(filename, sheets, "No interface index found")

    frame = pd.read_excel(excel_file, sheet_name=index_sheet, header=None, dtype=object)
    grid = [list(row) for row in frame.itertuples(index=False)]

    header = _find_header(grid)
    if header is None:
        return _sheet_fallback_payload(
            filename,
            sheets,
            f"The '{index_sheet}' sheet has no \"IBP Record\" column",
            exclude=index_sheet,
        )
    header_row, record_col, sheet_col = header

    warnings: list[str] = []
    records: list[str] = []
    declared: list[str] = []
    seen_records: set[str] = set()
    duplicates: list[str] = []

    for row in grid[header_row + 1 :]:
        record = _cell(row[record_col]) if record_col < len(row) else ""
        if not record:
            continue
        key = _norm(record)
        # IBP data records are unique by construction; a repeat means the index
        # itself is malformed. Keep the first and say so rather than silently
        # collapsing two rows into one interface.
        if key in seen_records:
            duplicates.append(record)
            continue
        seen_records.add(key)
        records.append(record)
        declared.append(
            _cell(row[sheet_col]) if sheet_col is not None and sheet_col < len(row) else ""
        )

    if duplicates:
        warnings.append(
            f"Duplicate IBP Record {'values' if len(duplicates) > 1 else 'value'} in "
            f"'{index_sheet}' ({', '.join(sorted(set(duplicates)))}) — kept the first "
            "occurrence of each."
        )

    if not records:
        return _sheet_fallback_payload(
            filename,
            sheets,
            f"The '{index_sheet}' sheet lists no interfaces",
            exclude=index_sheet,
        )

    # The index sheet itself is never one of the interface worksheets.
    candidates = [s for s in sheets if s != index_sheet]

    interfaces: list[dict[str, Any]] = []
    for record, declared_sheet, slug in zip(records, declared, _interface_ids(records)):
        if declared_sheet:
            # An explicit Sheet/Tab column is authoritative — resolve it against
            # the real sheet names (tolerating case/punctuation drift) and
            # report it broken if the workbook has no such sheet.
            hit = next((s for s in candidates if _norm(s) == _norm(declared_sheet)), None)
            sheet, match, competing = (
                (hit, "declared", []) if hit else (None, "none", [])
            )
        else:
            sheet, match, competing = _resolve_sheet(record, candidates)

        interfaces.append(
            {
                "id": slug,
                "record": record,
                "sheet": sheet,
                "status": "ok" if sheet else "broken",
                "match": match,
                "candidates": competing,
            }
        )

    broken = [i for i in interfaces if i["status"] == "broken"]
    if broken:
        warnings.append(
            f"{len(broken)} of {len(interfaces)} interfaces could not be matched to a "
            f"worksheet: {', '.join(i['record'] for i in broken)}."
        )

    return {
        "sheets": sheets,
        "index_sheet": index_sheet,
        "record_column": _cell(grid[header_row][record_col]),
        "sheet_column": (
            _cell(grid[header_row][sheet_col]) if sheet_col is not None else None
        ),
        "interfaces": interfaces,
        "indexed": True,
        "single_sheet": False,
        "warnings": warnings,
    }
