from __future__ import annotations

import pandas as pd

from backend.recon_engine.matching.location import _embedded_match, match_locations
from backend.recon_engine.models.value_mapping import Confidence

# The 5 real embedded matches measured against the actual S4/IBP export data
# (Phase 1) — the boundary hardening in Rule 2 must still catch every one of
# these, unchanged, or it has regressed.
REAL_EMBEDDED_CASES = [
    ("5001", "PL5001@S21400"),
    ("5006", "PL5006@S21400"),
    ("7000", "PL7000@S21400"),
    ("S101", "DCS101@S21400"),
    ("S102", "DCS102@S21400"),
]


def _match(mapping, source_value):
    return next(m for m in mapping.matches if m.source_value == source_value)


def test_rule1_exact_match():
    mapping = match_locations(
        source_plant=pd.Series(["PL01"]),
        target_locid=pd.Series(["PL01"]),
    )
    m = _match(mapping, "PL01")
    assert m.confidence == Confidence.VERY_HIGH
    assert m.rule == "location.rule1_exact_id"
    assert m.target_value == "PL01"


def test_rule2_embedded_in_locid():
    mapping = match_locations(
        source_plant=pd.Series(["S101"]),
        target_locid=pd.Series(["DCS101@S21400"]),
    )
    m = _match(mapping, "S101")
    assert m.confidence == Confidence.HIGH
    assert m.rule == "location.rule2_embedded_code"
    assert m.target_value == "DCS101@S21400"
    assert "LOCID" in m.evidence


def test_rule2_embedded_in_locname_when_locid_has_no_hit():
    mapping = match_locations(
        source_plant=pd.Series(["S101"]),
        target_locid=pd.Series(["LOC-9"]),
        target_alt_names=[pd.Series(["DC - S101"], name="LOCNAME")],
    )
    m = _match(mapping, "S101")
    assert m.confidence == Confidence.HIGH
    assert m.rule == "location.rule2_embedded_code"
    assert m.target_value == "LOC-9"  # resolved back to the LOCID, not the name
    assert "LOCNAME" in m.evidence


def test_rule3_no_match():
    mapping = match_locations(
        source_plant=pd.Series(["B301"]),
        target_locid=pd.Series(["PL01", "S501"]),
    )
    m = _match(mapping, "B301")
    assert m.confidence == Confidence.NONE
    assert m.rule == "location.rule3_no_match"


def test_override_wins_over_every_rule():
    mapping = match_locations(
        source_plant=pd.Series(["B301"]),
        target_locid=pd.Series(["PL01"]),
        overrides={"B301": "PL01"},
    )
    m = _match(mapping, "B301")
    assert m.confidence == Confidence.VERY_HIGH
    assert m.rule == "location.override"
    assert m.target_value == "PL01"


def test_determinism_two_runs_identical():
    kwargs = dict(
        source_plant=pd.Series(["PL01", "S101", "B301", "5006"]),
        target_locid=pd.Series(["PL01", "DCS101@S21400", "PL5006@S21400"]),
        target_alt_names=[
            pd.Series(["Vendor1-Alternate Supplier B", "DC - S101", "PL - 5006"], name="LOCNAME")
        ],
    )
    first = match_locations(**kwargs)
    second = match_locations(**kwargs)
    assert first.model_dump() == second.model_dump()


# ---- Rule 2 boundary hardening: regression + the false-positive it now blocks ----


def test_embedded_match_boundary_rejects_fragment_of_a_longer_number():
    # Plant "01" must NOT be considered "embedded" in an unrelated "2010" —
    # it's a slice of a bigger number, not the same code.
    assert _embedded_match("01", "2010") is False


def test_embedded_match_boundary_accepts_letter_adjacency():
    # Real data shape: plant code directly follows an org prefix ("DC", "PL")
    # with no separator — must still match.
    assert _embedded_match("S101", "DCS101@S21400") is True
    assert _embedded_match("5006", "PL5006@S21400") is True


def test_boundary_hardening_still_catches_all_five_real_embedded_matches():
    for plant, locid in REAL_EMBEDDED_CASES:
        assert _embedded_match(plant, locid) is True, f"{plant!r} should still embed in {locid!r}"

        mapping = match_locations(
            source_plant=pd.Series([plant]),
            target_locid=pd.Series([locid]),
        )
        m = _match(mapping, plant)
        assert m.confidence == Confidence.HIGH
        assert m.rule == "location.rule2_embedded_code"
        assert m.target_value == locid


def test_boundary_hardening_does_not_spuriously_match_digit_fragment_among_real_locids():
    # None of the real "no match" plants (Phase 1) should spuriously match any
    # of the real LOCID strings just because their digits happen to overlap.
    real_locids = [
        "DCS102@S21400", "PL5006@S21400", "DCS101@S21400", "PL7000@S21400",
        "Simplot_DC_UK", "Simplot_DC_US", "PL01", "PL5001@S21400",
        "VMI Customer 1", "S501",
    ]
    no_match_plants = [
        "0001", "1002", "1003", "4413", "5002", "5003", "5004", "5005",
        "B101", "B102", "B301", "B302", "PL10", "S201", "S301", "S401",
    ]
    for plant in no_match_plants:
        for locid in real_locids:
            assert _embedded_match(plant, locid) is False, f"{plant!r} spuriously embeds in {locid!r}"
