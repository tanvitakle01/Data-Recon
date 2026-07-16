from __future__ import annotations

import pandas as pd

from backend.recon_engine.matching import match_locations, match_products
from backend.recon_engine.models.value_mapping import (
    AUTO_APPLY_CONFIDENCE,
    HOLD_OUT_CONFIDENCE,
    Confidence,
    ValueMapping,
)


def test_package_exports_both_matchers():
    # `backend.recon_engine.matching` is the public surface the rest of the
    # engine (and callers) import from — pin it so a refactor can't quietly
    # drop one of the two matchers from `__all__`.
    from backend.recon_engine import matching

    assert set(matching.__all__) == {"match_locations", "match_products"}


def test_confidence_tiers_are_disjoint_and_cover_auto_apply_and_hold_out():
    # Two buckets only: AUTO_APPLY (VERY_HIGH/HIGH) vs everything else held out
    # (MEDIUM/NONE/OUT_OF_SCOPE) — no separate "needs review" tier.
    all_tiers = set(Confidence)
    assert AUTO_APPLY_CONFIDENCE.isdisjoint(HOLD_OUT_CONFIDENCE)
    assert Confidence.MEDIUM in HOLD_OUT_CONFIDENCE
    assert AUTO_APPLY_CONFIDENCE | HOLD_OUT_CONFIDENCE == all_tiers


def test_both_matchers_return_value_mapping_for_their_declared_field_pair():
    product = match_products(
        source_material=pd.Series(["MAT-1"]),
        source_material_group=None,
        target_prdid=pd.Series(["MAT-1"]),
    )
    location = match_locations(
        source_plant=pd.Series(["PL01"]),
        target_locid=pd.Series(["PL01"]),
    )
    assert isinstance(product, ValueMapping)
    assert (product.source_field, product.target_field) == ("Material", "PRDID")
    assert isinstance(location, ValueMapping)
    assert (location.source_field, location.target_field) == ("ProductionPlant", "LOCID")


def test_engine_wide_determinism_across_both_matchers():
    # Same shape as the per-module determinism tests, but run together as the
    # engine actually would be invoked (one call per key field, same inputs).
    product_kwargs = dict(
        source_material=pd.Series(["MAT-1", "RAW-1", "GHOST"]),
        source_material_group=pd.Series(["FG", "RM", None]),
        target_prdid=pd.Series(["MAT-1"]),
        target_prodgroup=pd.Series(["FG"]),
    )
    location_kwargs = dict(
        source_plant=pd.Series(["PL01", "S101", "B301"]),
        target_locid=pd.Series(["PL01", "DCS101@S21400"]),
    )

    run1 = (
        match_products(**product_kwargs).model_dump(),
        match_locations(**location_kwargs).model_dump(),
    )
    run2 = (
        match_products(**product_kwargs).model_dump(),
        match_locations(**location_kwargs).model_dump(),
    )
    assert run1 == run2


def test_held_out_matches_includes_medium_none_and_out_of_scope():
    mapping = match_products(
        source_material=pd.Series(["EXACT", "RAW-1", "AMBIG", "GHOST"]),
        source_material_group=pd.Series(["FG", "RM", None, None]),
        target_prdid=pd.Series(["EXACT", "PRD-1", "PRD-2"]),
        target_prodgroup=pd.Series(["FG", "FG", "FG"]),
        target_proddesc=pd.Series([None, "Dough", "Dough"]),
        source_order_item_text=pd.Series([None, None, "dough", None]),
    )
    held_out = {m.source_value for m in mapping.held_out_matches()}
    applied = mapping.executable_mapping()

    # OUT_OF_SCOPE, NONE, and MEDIUM (ambiguous, never auto-applied) are all
    # held out — there's no separate "needs review" bucket anymore.
    assert held_out == {"RAW-1", "GHOST", "AMBIG"}
    assert applied == {"EXACT": "EXACT"}  # only VERY_HIGH/HIGH with a real target
