"""Workbook interface index: which interfaces a mapping workbook holds.

Covers index-sheet discovery, IBP-Record extraction, and every record -> sheet
resolution outcome (exact, substring, declared, missing, ambiguous) — including
the ones that must degrade rather than crash.
"""

from __future__ import annotations

from io import BytesIO

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.recon_engine.interface_index import find_index_sheet, read_interface_index
from backend.routes.contracts import router


def _workbook(sheets: dict[str, list[list]]) -> bytes:
    """Write a multi-sheet xlsx with no header row assumption."""
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for name, rows in sheets.items():
            pd.DataFrame(rows).to_excel(writer, sheet_name=name, header=False, index=False)
    return buf.getvalue()


def _field_table() -> list[list]:
    """A minimal interface worksheet — never read by the index reader."""
    return [
        ["Target: IBP", None, "Source: S4"],
        ["Target fields", "Technical fields", "Source Table/Field"],
        ["Product ID", "PRDID", "VBAP-MATNR"],
    ]


# ── index-sheet discovery ────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "name",
    ["Interfaces", "interfaces", "Interface", "Interfaces List", "interface list", "InterfacesList"],
)
def test_index_sheet_name_variants_match(name):
    assert find_index_sheet(["Cover", name, "Data"]) == name


@pytest.mark.parametrize("name", ["Interfacing", "Interfaces Detail", "Mapping", "IBP Interfaces"])
def test_unrelated_sheet_names_do_not_match(name):
    assert find_index_sheet(["Cover", name]) is None


# ── the happy path ───────────────────────────────────────────────────────────

def test_interfaces_extracted_in_row_order_and_resolved_exactly():
    # The records the index sheet lists, and the worksheet each should resolve
    # to. Both expectations below are derived from this, so the test asserts
    # "whatever the column lists, in that order" rather than a fixed set.
    listed = {
        "Sales Order History": "Sales Order History",  # normalised-exact
        "Available Stock": "AvailableStock",  # exact once punctuation is dropped
        "Product Master": "Product Master",
    }
    content = _workbook(
        {
            "Interfaces": [
                ["Scope: SAP S/4 -> IBP"],
                ["#", "IBP Data Record", "Owner"],
                *([n, record, "owner"] for n, record in enumerate(listed, start=1)),
                [None, None, None],  # a blank row mid-list
            ],
            **{sheet: _field_table() for sheet in listed.values()},
        }
    )
    index = read_interface_index(content, filename="workbook.xlsx")

    assert index["indexed"] is True
    assert index["index_sheet"] == "Interfaces"
    assert index["record_column"] == "IBP Data Record"
    assert index["sheet_column"] is None
    # Blank rows are skipped, not turned into empty interfaces.
    assert [i["record"] for i in index["interfaces"]] == list(listed)
    assert [i["sheet"] for i in index["interfaces"]] == list(listed.values())
    assert all(i["status"] == "ok" and i["match"] == "exact" for i in index["interfaces"])
    assert index["warnings"] == []


def test_interface_id_matches_the_historical_comparison_type_slug():
    content = _workbook(
        {
            "Interfaces": [["IBP Record"], ["Sales Order History"]],
            "Sales Order History": _field_table(),
        }
    )
    index = read_interface_index(content, filename="workbook.xlsx")
    assert index["interfaces"][0]["id"] == "salesorderhistory"


def test_ibp_record_header_variants():
    for header in ("IBP Record", "IBP Data Record", "IBPDataRecord"):
        content = _workbook(
            {
                "Interfaces": [[header], ["Available Stock"]],
                "Available Stock": _field_table(),
            }
        )
        index = read_interface_index(content, filename="w.xlsx")
        assert [i["record"] for i in index["interfaces"]] == ["Available Stock"], header


# ── record -> sheet resolution ───────────────────────────────────────────────

def test_unique_substring_match_resolves():
    content = _workbook(
        {
            "Interfaces": [["IBP Record"], ["Product Master"]],
            "Product Master Data": _field_table(),
        }
    )
    index = read_interface_index(content, filename="w.xlsx")
    assert index["interfaces"][0]["sheet"] == "Product Master Data"
    assert index["interfaces"][0]["match"] == "substring"


def test_missing_sheet_is_flagged_broken_not_raised():
    content = _workbook(
        {
            "Interfaces": [["IBP Record"], ["Sales Order History"], ["Location Master"]],
            "Sales Order History": _field_table(),
        }
    )
    index = read_interface_index(content, filename="w.xlsx")

    ok, broken = index["interfaces"]
    assert ok["status"] == "ok"
    assert broken["record"] == "Location Master"
    assert broken["status"] == "broken"
    assert broken["match"] == "none"
    assert broken["sheet"] is None
    assert "Location Master" in index["warnings"][0]


def test_ambiguous_match_is_broken_and_names_its_candidates():
    content = _workbook(
        {
            "Interfaces": [["IBP Record"], ["Stock"]],
            "Stock Daily": _field_table(),
            "Stock Weekly": _field_table(),
        }
    )
    index = read_interface_index(content, filename="w.xlsx")

    iface = index["interfaces"][0]
    assert iface["status"] == "broken"
    assert iface["match"] == "ambiguous"
    assert sorted(iface["candidates"]) == ["Stock Daily", "Stock Weekly"]


def test_a_punctuation_only_sheet_does_not_match_every_record():
    """A divider sheet normalises to "" — which is a substring of everything.

    Left unguarded it matches every record: "Product Master" would resolve
    ambiguously between the real sheet and the divider, and a record with no
    real match at all would resolve TO the divider.
    """
    content = _workbook(
        {
            "Interfaces": [["IBP Record"], ["Product Master"], ["Nothing Like It"]],
            "---": _field_table(),  # a legal Excel sheet name, all punctuation
            "Product Master Data": _field_table(),
        }
    )
    index = read_interface_index(content, filename="w.xlsx")

    resolved, unmatched = index["interfaces"]
    assert resolved["sheet"] == "Product Master Data"
    assert resolved["match"] == "substring"
    # The divider is not a plausible home for a record that matches nothing.
    assert unmatched["status"] == "broken"
    assert unmatched["match"] == "none"
    assert unmatched["sheet"] is None


def test_interface_ids_stay_unique_when_a_suffix_would_itself_collide():
    """["X", "X2", "X."] must not hand two interfaces the id "x2".

    The UI resolves a Dataset Type selection by id alone, so a duplicate id
    silently parses the other interface's worksheet.
    """
    sheets = ["X", "X2", "X."]
    content = _workbook({name: _field_table() for name in sheets})
    index = read_interface_index(content, filename="w.xlsx")

    ids = [i["id"] for i in index["interfaces"]]
    assert len(ids) == len(sheets)
    assert len(set(ids)) == len(ids), ids


def test_declared_sheet_column_is_authoritative():
    content = _workbook(
        {
            "Interfaces": [
                ["IBP Record", "Sheet"],
                ["Available Stock", "AS_v3"],
                ["Product Master", "Nope"],
            ],
            # A sheet that WOULD have matched "Available Stock" by name — the
            # declared column must win over it.
            "AvailableStock": _field_table(),
            "AS_v3": _field_table(),
            "Product Master": _field_table(),
        }
    )
    index = read_interface_index(content, filename="w.xlsx")

    assert index["sheet_column"] == "Sheet"
    assert index["interfaces"][0]["sheet"] == "AS_v3"
    assert index["interfaces"][0]["match"] == "declared"
    # A declared sheet the workbook doesn't have is broken, NOT re-guessed by
    # name — even though "Product Master" would have matched exactly.
    assert index["interfaces"][1]["status"] == "broken"


def test_index_sheet_is_never_itself_an_interface_sheet():
    content = _workbook(
        {
            "Interfaces": [["IBP Record"], ["Interfaces"]],
            "Data": _field_table(),
        }
    )
    index = read_interface_index(content, filename="w.xlsx")
    assert index["interfaces"][0]["status"] == "broken"


def test_duplicate_record_keeps_the_first_and_warns():
    content = _workbook(
        {
            "Interfaces": [
                ["IBP Record", "Sheet"],
                ["Available Stock", "First"],
                ["available  stock", "Second"],
            ],
            "First": _field_table(),
            "Second": _field_table(),
        }
    )
    index = read_interface_index(content, filename="w.xlsx")

    assert len(index["interfaces"]) == 1
    assert index["interfaces"][0]["sheet"] == "First"
    assert "Duplicate IBP Record" in index["warnings"][0]


# ── worksheet-name fallback ──────────────────────────────────────────────────
# No usable index => every worksheet is offered as an interface. The workbook
# is never reduced to just its first sheet.

def test_no_index_sheet_offers_every_worksheet():
    sheets = ["Sales Order History", "Product Master", "Available Stock"]
    content = _workbook({name: _field_table() for name in sheets})
    index = read_interface_index(content, filename="w.xlsx")

    assert index["indexed"] is False
    assert index["index_sheet"] is None
    # The workbook's OWN sheet list is the interface list. Asserted as an
    # identity against what the read reported finding in the document, so the
    # test can't pass by matching a fixed set of names.
    assert [i["record"] for i in index["interfaces"]] == index["sheets"]
    # Each is runnable and points at the sheet its name came from.
    assert all(i["status"] == "ok" and i["sheet"] == i["record"] for i in index["interfaces"])
    assert all(i["match"] == "sheet" for i in index["interfaces"])
    assert index["warnings"] == [
        f"No interface index found — listing all {len(sheets)} worksheets as interfaces."
    ]


def test_fallback_is_agnostic_to_what_the_sheets_are_called():
    """No interface name is known to the code — only the document supplies them."""
    sheets = ["Zeta Flow", "alpha-feed", "wk 42 (draft)", "untitled_3"]
    content = _workbook({name: _field_table() for name in sheets})
    index = read_interface_index(content, filename="w.xlsx")

    assert [i["record"] for i in index["interfaces"]] == index["sheets"]
    assert all(i["status"] == "ok" for i in index["interfaces"])
    # Ids are derived from those names, unique, and never empty.
    ids = [i["id"] for i in index["interfaces"]]
    assert len(set(ids)) == len(ids)
    assert all(ids)


def test_index_sheet_without_a_record_column_offers_every_other_worksheet():
    index_name = "Interfaces"
    content = _workbook(
        {
            index_name: [["Name", "Owner"], ["Sales", "planning"]],
            "Sales Order History": _field_table(),
            "Product Master": _field_table(),
        }
    )
    index = read_interface_index(content, filename="w.xlsx")

    assert index["indexed"] is False
    # Every sheet the document has, minus the one positively identified as the
    # index itself — derived from the reported sheet list, not a fixed set.
    expected = [s for s in index["sheets"] if s != index_name]
    assert [i["record"] for i in index["interfaces"]] == expected
    assert "IBP Record" in index["warnings"][0]
    assert f"all {len(expected)} worksheets" in index["warnings"][0]


def test_empty_index_sheet_offers_every_other_worksheet():
    index_name = "Interfaces"
    content = _workbook(
        {
            index_name: [["IBP Record"], [None]],
            "Sales Order History": _field_table(),
            "Product Master": _field_table(),
        }
    )
    index = read_interface_index(content, filename="w.xlsx")

    assert index["indexed"] is False
    assert [i["record"] for i in index["interfaces"]] == [
        s for s in index["sheets"] if s != index_name
    ]
    assert "lists no interfaces" in index["warnings"][0]


# ── single-sheet upload ──────────────────────────────────────────────────────
# One sheet => that sheet IS the dataset. A first-class shape (the user
# exported one interface rather than the project workbook), so it reports no
# index, no choice and — critically — no warning.

def test_one_sheet_upload_is_the_dataset_with_no_warning():
    content = _workbook({"Sales Order History": _field_table()})
    index = read_interface_index(content, filename="w.xlsx")

    assert index["single_sheet"] is True
    assert index["indexed"] is False
    assert index["index_sheet"] is None
    assert len(index["interfaces"]) == 1
    iface = index["interfaces"][0]
    # The sheet names the dataset, and it is the sheet handed to the parse.
    assert iface["record"] == index["sheets"][0] == "Sales Order History"
    assert iface["sheet"] == "Sales Order History"
    assert iface["status"] == "ok"
    assert iface["match"] == "single"
    # The absence of an index is this upload's expected shape, not a problem.
    assert index["warnings"] == []


def test_one_sheet_upload_keeps_the_historical_comparison_type_slug():
    content = _workbook({"Sales Order History": _field_table()})
    index = read_interface_index(content, filename="w.xlsx")
    assert index["interfaces"][0]["id"] == "salesorderhistory"


@pytest.mark.parametrize("sheet", ["Sheet1", "sheet", "Tab 2", "worksheet", "Data"])
def test_a_default_sheet_name_falls_back_to_the_filename(sheet):
    """"Sheet1" names nothing — the file the user chose does."""
    content = _workbook({sheet: _field_table()})
    index = read_interface_index(content, filename="Sales Order History.xlsx")

    iface = index["interfaces"][0]
    assert iface["record"] == "Sales Order History"
    # Only the LABEL falls back — the sheet handed to the parse is still the
    # workbook's own. Asserted against what the read reports, since openpyxl
    # normalises some written names (a sheet asked to be "sheet" comes back
    # "sheet1"), which is the fixture's business and not this module's.
    assert len(index["sheets"]) == 1
    assert iface["sheet"] == index["sheets"][0]


def test_one_sheet_upload_named_interfaces_is_still_the_dataset():
    """The degenerate case index detection alone would resolve to nothing.

    "Interfaces" is claimed as the index sheet, then excluded from its own
    candidate list — leaving every record unmatched and the upload unusable.
    The single-sheet short-circuit runs first, so it stays a valid dataset.
    """
    content = _workbook({"Interfaces": _field_table()})
    index = read_interface_index(content, filename="w.xlsx")

    assert index["single_sheet"] is True
    assert index["index_sheet"] is None
    assert [i["status"] for i in index["interfaces"]] == ["ok"]
    assert index["interfaces"][0]["sheet"] == "Interfaces"


def test_csv_upload_is_a_single_sheet_dataset():
    index = read_interface_index(b"a,b\n1,2\n", filename="mapping.csv")

    assert index["single_sheet"] is True
    assert index["indexed"] is False
    assert len(index["interfaces"]) == 1
    # Labelled by the file, minus the extension; the parse still receives the
    # filename as the "sheet", which is what the CSV reader expects.
    assert index["interfaces"][0]["record"] == "mapping"
    assert index["interfaces"][0]["sheet"] == "mapping.csv"
    assert index["warnings"] == []


def test_multi_sheet_workbook_is_not_treated_as_single_sheet():
    """The short-circuit must not swallow the worksheet-name fallback."""
    content = _workbook(
        {"Sales Order History": _field_table(), "Product Master": _field_table()}
    )
    index = read_interface_index(content, filename="w.xlsx")

    assert index["single_sheet"] is False
    assert len(index["interfaces"]) == 2
    assert index["warnings"]  # still says why there is no index


def test_fallback_route_lists_the_documents_sheet_names():
    content = _workbook(
        {"Sales Order History": _field_table(), "Product Master": _field_table()}
    )
    res = _client().post(
        "/api/recon/mapping-sheet/interfaces",
        files={"file": ("workbook.xlsx", content, "application/vnd.ms-excel")},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["indexed"] is False
    # Every sheet the document reports having is offered as an interface.
    assert [i["record"] for i in body["interfaces"]] == body["sheets"]


def test_unreadable_file_raises_valueerror():
    with pytest.raises(ValueError, match="Unable to read"):
        read_interface_index(b"not a workbook", filename="w.xlsx")


# ── the route ────────────────────────────────────────────────────────────────

def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_interfaces_route_returns_the_index():
    content = _workbook(
        {
            "Interfaces": [["IBP Data Record"], ["Sales Order History"], ["Location Master"]],
            "Sales Order History": _field_table(),
        }
    )
    res = _client().post(
        "/api/recon/mapping-sheet/interfaces",
        files={"file": ("workbook.xlsx", content, "application/vnd.ms-excel")},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["filename"] == "workbook.xlsx"
    assert body["indexed"] is True
    assert [i["status"] for i in body["interfaces"]] == ["ok", "broken"]


def test_interfaces_route_rejects_an_empty_upload():
    res = _client().post(
        "/api/recon/mapping-sheet/interfaces",
        files={"file": ("empty.xlsx", b"", "application/vnd.ms-excel")},
    )
    assert res.status_code == 400
    assert "empty" in res.json()["detail"].lower()


def test_parse_route_still_slices_one_named_sheet():
    """The interpretation step's input scope: exactly the chosen worksheet."""
    content = _workbook(
        {
            "Interfaces": [["IBP Record"], ["Available Stock"]],
            "Available Stock": _field_table(),
            "Other Interface": [["Target fields"], ["Should not appear"]],
        }
    )
    res = _client().post(
        "/api/recon/mapping-sheet/parse",
        files={"file": ("workbook.xlsx", content, "application/vnd.ms-excel")},
        data={"sheet_name": "Available Stock"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["sheet_name"] == "Available Stock"
    assert body["rows"] == [
        {"Target fields": "Product ID", "Technical fields": "PRDID", "Source Table/Field": "VBAP-MATNR"}
    ]
