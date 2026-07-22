"""MDT Auxiliary Field Recommender + matcher consumption of ranked lists.

Covers: fuzzy existence, population (0%-fill exclusion) with real fill-rate
numbers, tier fall-through, the consumed flag, and that the widened matchers
actually iterate the ranked auxiliary lists. The evidence-only boundary (aux
fields never leak into the mapping output) is asserted in
test_value_mapping_route.py's aux additions.
"""

from __future__ import annotations

import pandas as pd

from backend.recon_engine.matching import (
    TARGET_LOCATION_SEEDS,
    TARGET_PRODUCT_SEEDS,
    confirmed_series,
    first_confirmed_series,
    match_locations,
    match_products,
    recommend_auxiliary_fields,
)
from backend.recon_engine.matching.auxiliary import (
    ROLE_LOCATION_ALT_NAME,
    ROLE_LOCATION_VALIDATION,
    ROLE_PRODUCT_GROUP,
    SOURCE_PLANT_SEEDS,
)
from backend.recon_engine.models.value_mapping import Confidence


def _rec(df, seeds, seed_name):
    recs = recommend_auxiliary_fields(df, seeds)
    return next(r for r in recs if r.seed_name == seed_name)


# ── existence (fuzzy / case-insensitive) ─────────────────────────────────────

def test_existence_is_case_insensitive_and_fuzzy():
    # Real schemas vary in casing/spacing — "proddesc" must resolve to PRODDESC.
    df = pd.DataFrame({"proddesc": ["Widget"], "PROD_GROUP": ["FG"], "PRDID": ["P1"]})
    proddesc = _rec(df, TARGET_PRODUCT_SEEDS, "PRODDESC")
    assert proddesc.confirmed_existing is True
    assert proddesc.resolved_name == "proddesc"
    prodgroup = _rec(df, TARGET_PRODUCT_SEEDS, "PRODGROUP")
    assert prodgroup.confirmed_existing is True
    assert prodgroup.resolved_name == "PROD_GROUP"


def test_absent_attribute_is_not_confirmed():
    df = pd.DataFrame({"PRDID": ["P1"]})
    sprdid = _rec(df, TARGET_PRODUCT_SEEDS, "SPRDID")
    assert sprdid.confirmed_existing is False
    assert sprdid.resolved_name is None
    assert sprdid.confirmed is False
    assert sprdid.fill_rate is None


# ── population (0%-fill exclusion) with real fill-rate numbers ────────────────

def test_zero_fill_column_is_not_recommended():
    # PRDIDDEM present but entirely blank (the documented real-data shape).
    df = pd.DataFrame({"PRDID": ["P1", "P2"], "PRDIDDEM": [None, ""]})
    prdiddem = _rec(df, TARGET_PRODUCT_SEEDS, "PRDIDDEM")
    assert prdiddem.confirmed_existing is True
    assert prdiddem.confirmed_populated is False
    assert prdiddem.fill_rate == 0.0
    assert prdiddem.confirmed is False


def test_fill_rate_is_reported_accurately():
    # 3 of 4 rows populated (blank = None/""/whitespace via _is_blank).
    df = pd.DataFrame({"PRDID": list("abcd"), "PRODDESC": ["x", "", "y", "z"]})
    proddesc = _rec(df, TARGET_PRODUCT_SEEDS, "PRODDESC")
    assert proddesc.confirmed_populated is True
    assert proddesc.fill_rate == 0.75


# ── tier fall-through ────────────────────────────────────────────────────────

def test_tier2_falls_through_when_tier1_absent():
    # PRODGROUP (tier 1) absent; PRODGROUPDEM (tier 2) present+populated → the
    # single best group Series resolves to the tier-2 field.
    df = pd.DataFrame({"PRDID": ["P1"], "PRODGROUPDEM": ["FG"]})
    recs = recommend_auxiliary_fields(df, TARGET_PRODUCT_SEEDS)
    best = first_confirmed_series(df, recs, ROLE_PRODUCT_GROUP)
    assert best is not None
    assert best.name == "PRODGROUPDEM"


def test_tier1_preferred_over_tier2_when_both_present():
    df = pd.DataFrame({"PRDID": ["P1"], "PRODGROUP": ["FG"], "PRODGROUPDEM": ["FG2"]})
    recs = recommend_auxiliary_fields(df, TARGET_PRODUCT_SEEDS)
    picks = confirmed_series(df, recs, ROLE_PRODUCT_GROUP)
    assert [s.name for s in picks] == ["PRODGROUP", "PRODGROUPDEM"]  # tier-ranked


# ── consumed flag ────────────────────────────────────────────────────────────

def test_consumed_flag_distinguishes_wired_vs_validation_only():
    df = pd.DataFrame({"LOCID": ["L1"], "LOCNAME": ["DC S101"], "LOCATIONTYPE": ["Plant"]})
    locname = _rec(df, TARGET_LOCATION_SEEDS, "LOCNAME")
    loctype = _rec(df, TARGET_LOCATION_SEEDS, "LOCATIONTYPE")
    assert locname.role == ROLE_LOCATION_ALT_NAME and locname.consumed is True
    assert loctype.role == ROLE_LOCATION_VALIDATION and loctype.consumed is False


def test_source_plant_original_plant_fill_rate_rechecked():
    # OriginalPlant sparse on real data — the recommender must re-verify, not assume.
    df = pd.DataFrame({"ProductionPlant": ["S101", "S102"], "OriginalPlant": ["", ""]})
    op = _rec(df, SOURCE_PLANT_SEEDS, "OriginalPlant")
    assert op.confirmed_existing is True
    assert op.confirmed_populated is False  # 0% filled → not recommended


# ── matcher consumption of the ranked lists ──────────────────────────────────

def test_location_rule2_uses_tier_ranked_alt_names_and_cites_the_field():
    # LOCID no embed, LOCNAME no embed, LOCDESCRDEM embeds the plant code → the
    # matcher must fall through the ranked list and cite LOCDESCRDEM.
    mapping = match_locations(
        source_plant=pd.Series(["S101"]),
        target_locid=pd.Series(["LOC-1"]),
        target_alt_names=[
            pd.Series(["Unrelated Name"], name="LOCNAME"),
            pd.Series(["Distribution S101 UK"], name="LOCDESCRDEM"),
        ],
    )
    m = next(x for x in mapping.matches if x.source_value == "S101")
    assert m.confidence == Confidence.HIGH
    assert m.rule == "location.rule2_embedded_code"
    assert m.target_value == "LOC-1"  # resolved back to LOCID
    assert "LOCDESCRDEM" in m.evidence  # cites which alt-name field matched


def test_product_rule4_uses_ranked_alt_ids_and_cites_the_field():
    # PRDIDDEM empty, SPRDID carries the alternate id → match cites SPRDID.
    mapping = match_products(
        source_material=pd.Series(["ALT-9"]),
        source_material_group=None,
        target_prdid=pd.Series(["PRD-2"]),
        target_alt_ids=[
            pd.Series([None], name="PRDIDDEM"),
            pd.Series(["ALT-9"], name="SPRDID"),
        ],
    )
    m = next(x for x in mapping.matches if x.source_value == "ALT-9")
    assert m.rule == "product.rule4_alternate_id"
    assert m.target_value == "PRD-2"
    assert "SPRDID" in m.evidence


def test_product_rule5_unions_multiple_description_columns():
    # The bridge must reach a PRDID whose description lives in the SECOND
    # description column (PRODDESCDEM), not just the first (PRODDESC).
    mapping = match_products(
        source_material=pd.Series(["MAT-X"]),
        source_material_group=None,
        target_prdid=pd.Series(["PRD-1"]),
        target_descriptions=[
            pd.Series(["something else"], name="PRODDESC"),
            pd.Series(["Chocolate"], name="PRODDESCDEM"),
        ],
        source_order_item_text=pd.Series(["chocolate"]),
    )
    m = next(x for x in mapping.matches if x.source_value == "MAT-X")
    assert m.rule == "product.rule5_description_match"
    assert m.target_value == "PRD-1"
