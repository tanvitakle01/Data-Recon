"""Deterministic mapping-sheet parser: simple templates AND enterprise workbooks."""

from __future__ import annotations

from io import BytesIO

import pandas as pd
import pytest

from backend.recon_engine.compiler.stub_compiler import StubContractCompiler
from backend.recon_engine.mapping_sheet_parser import parse_mapping_sheet


def _xlsx_bytes(rows: list[list], sheet_name: str = "Sheet1") -> bytes:
    buf = BytesIO()
    df = pd.DataFrame(rows)
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=sheet_name, header=False, index=False)
    return buf.getvalue()


# ── simple template ──────────────────────────────────────────────────────────

def test_simple_template_headers_in_first_row():
    content = _xlsx_bytes(
        [
            ["Source_Field", "Target_Field", "Transformation_Rule"],
            ["MATNR", "PRDID", "strip leading zeros"],
            ["WERKS", "LOCID", None],
        ],
        sheet_name="Mapping",
    )
    parsed = parse_mapping_sheet(content, filename="simple.xlsx")

    assert parsed["sheet_name"] == "Mapping"
    assert parsed["headers"] == ["Source_Field", "Target_Field", "Transformation_Rule"]
    assert parsed["row_count"] == 2
    assert parsed["rows"][0]["Source_Field"] == "MATNR"
    assert parsed["rows"][1]["Transformation_Rule"] is None

    candidates = parsed["mapping_candidates"]
    assert [(c["source_field"], c["target_field"]) for c in candidates] == [
        ("MATNR", "PRDID"),
        ("WERKS", "LOCID"),
    ]
    assert parsed["transformation_notes"][0]["text"] == "strip leading zeros"
    assert parsed["join_conditions"] == []
    assert parsed["filters"] == []


def test_csv_template():
    csv = (
        "Source Column,Target Column,Rule\n"
        "MATNR,PRDID,remove leading zeros\n"
        "WERKS,LOCID,\n"
    ).encode()
    parsed = parse_mapping_sheet(csv, filename="mapping.csv")

    assert parsed["headers"] == ["Source Column", "Target Column", "Rule"]
    assert len(parsed["mapping_candidates"]) == 2
    assert parsed["mapping_candidates"][0]["transformation"] == "remove leading zeros"


# ── enterprise SAP/IBP workbook ──────────────────────────────────────────────

ENTERPRISE_ROWS = [
    ["S/4HANA to IBP Field Mapping", None, None, None, None, None, None],
    [None, None, None, None, None, None, None],
    [
        "Target Fields", "Technical Field", "Source Table/Field",
        "Description", "Transformation", "Join Condition", "Filter",
    ],
    [
        "Product ID", "PRDID", "MARA-MATNR",
        "Material number", "Strip leading zeros; cast to string",
        "MARA-MATNR = MARC-MATNR", "MTART = 'FERT'",
    ],
    [
        "Location ID", "LOCID", "MARC-WERKS",
        "Plant", None, None, "WERKS <> '9999'",
    ],
    [None, None, None, None, None, None, None],
    [
        "Qty", "QTY", "VBAP-KWMENG",
        "Order quantity", "Sum per product/location", None, None,
    ],
]


def test_enterprise_workbook_banner_row_and_role_columns():
    content = _xlsx_bytes(ENTERPRISE_ROWS, sheet_name="SalesHistory")
    parsed = parse_mapping_sheet(content, filename="enterprise.xlsx")

    # Header detected below the banner row; banner preserved as metadata.
    assert parsed["metadata"]["header_row_index"] == 2
    assert parsed["metadata"]["preamble_rows"][0][0] == "S/4HANA to IBP Field Mapping"
    assert parsed["headers"][0] == "Target Fields"
    assert parsed["metadata"]["empty_row_indices"] == [5]

    # Lossless rows: every column preserved under its original header.
    assert parsed["row_count"] == 3
    assert parsed["rows"][0]["Source Table/Field"] == "MARA-MATNR"
    assert parsed["rows"][0]["Description"] == "Material number"

    detected = parsed["detected_columns"]
    assert detected["target"] == ["Target Fields"]
    assert detected["technical"] == ["Technical Field"]
    assert detected["source"] == ["Source Table/Field"]
    assert detected["description"] == ["Description"]
    assert detected["transformation"] == ["Transformation"]
    assert detected["join_condition"] == ["Join Condition"]
    assert detected["filter"] == ["Filter"]

    candidates = parsed["mapping_candidates"]
    assert len(candidates) == 3
    first = candidates[0]
    assert first["source_field"] == "MARA-MATNR"
    assert first["target_field"] == "Product ID"
    assert first["technical_field"] == "PRDID"
    assert first["description"] == "Material number"
    assert first["transformation"] == "Strip leading zeros; cast to string"
    assert first["join_condition"] == "MARA-MATNR = MARC-MATNR"
    assert first["filter"] == "MTART = 'FERT'"

    assert [n["text"] for n in parsed["transformation_notes"]] == [
        "Strip leading zeros; cast to string",
        "Sum per product/location",
    ]
    assert [n["text"] for n in parsed["join_conditions"]] == ["MARA-MATNR = MARC-MATNR"]
    assert [n["text"] for n in parsed["filters"]] == ["MTART = 'FERT'", "WERKS <> '9999'"]


def test_sheet_selection_and_unknown_sheet():
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame([["a", "b"]]).to_excel(writer, sheet_name="Cover", header=False, index=False)
        pd.DataFrame(
            [["Source Field", "Target Field"], ["MATNR", "PRDID"]]
        ).to_excel(writer, sheet_name="Mapping", header=False, index=False)
    content = buf.getvalue()

    parsed = parse_mapping_sheet(content, filename="wb.xlsx", sheet_name="Mapping")
    assert parsed["sheet_name"] == "Mapping"
    assert parsed["sheets"] == ["Cover", "Mapping"]
    assert parsed["mapping_candidates"][0]["source_field"] == "MATNR"

    with pytest.raises(ValueError):
        parse_mapping_sheet(content, filename="wb.xlsx", sheet_name="Nope")


# ── graceful degradation: no recognisable columns ────────────────────────────

def test_unrecognised_headers_stay_lossless_with_no_candidates():
    content = _xlsx_bytes(
        [
            ["Alpha", "Beta", "Gamma"],
            [1, 2.5, "x"],
            [3, None, "y"],
        ]
    )
    parsed = parse_mapping_sheet(content, filename="odd.xlsx")

    assert parsed["headers"] == ["Alpha", "Beta", "Gamma"]
    assert parsed["rows"] == [
        {"Alpha": 1, "Beta": 2.5, "Gamma": "x"},
        {"Alpha": 3, "Beta": None, "Gamma": "y"},
    ]
    assert parsed["mapping_candidates"] == []
    assert parsed["transformation_notes"] == []
    assert parsed["join_conditions"] == []
    assert parsed["filters"] == []


def test_duplicate_and_blank_headers_are_deduplicated():
    content = _xlsx_bytes(
        [
            ["Source Field", "Source Field", None],
            ["MATNR", "MARA", "note"],
        ]
    )
    parsed = parse_mapping_sheet(content, filename="dup.xlsx")
    assert parsed["headers"] == ["Source Field", "Source Field_2", "Column_3"]
    assert parsed["rows"][0]["Source Field_2"] == "MARA"


# ── downstream: stub compiler accepts the parsed payload ─────────────────────

def test_stub_compiler_accepts_parsed_payload():
    content = _xlsx_bytes(ENTERPRISE_ROWS)
    parsed = parse_mapping_sheet(content, filename="enterprise.xlsx")

    draft = StubContractCompiler().compile(
        mapping_sheet=parsed,
        rules="",
        source_schema=["MARA-MATNR", "MARC-WERKS", "VBAP-KWMENG"],
        target_schema=["Product ID", "Location ID", "Qty"],
        comparison_type="sales_history",
        source_type="s4",
        target_type="ibp",
    )
    pairs = {(k.source_field, k.target_field) for k in draft.business_key}
    assert ("MARA-MATNR", "Product ID") in pairs
    assert draft.compiler == "stub"
