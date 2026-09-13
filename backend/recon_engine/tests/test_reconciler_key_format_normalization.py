"""End-to-end regression coverage for the bug behind a real reconciliation
(ECC VBBE -> IBP SOPDD_STAGING_KFTAB) whose Shadow_Source built correctly
(right filter/aggregate row counts) but the FINAL reconcile showed 0 matches:
the business-key join compared raw, differently-formatted strings — an ISO
date against "M/D/YYYY", and a float-artifact ID ("786293.0") against plain
text ("786293") — so every key failed regardless of the underlying data
being correct. ``reconciler._build_key`` now canonicalizes each key field
(see ``engine.key_normalization``) before joining, independent of what
either side's original format was."""

from __future__ import annotations

import pandas as pd

from backend.recon_engine.engine.reconciler import reconcile
from backend.recon_engine.models.contract import TransformationContract


def _contract(**over) -> TransformationContract:
    base = dict(
        contract_id="c1",
        contract_version=1,
        comparison_type="sales_history",
        source_type="s4",
        target_type="ibp",
        operations=[],
        business_key=[
            {"source_field": "PRDID", "target_field": "PRDID"},
            {"source_field": "LOCID", "target_field": "LOCID"},
            {"source_field": "KEYFIGUREDATE", "target_field": "KEYFIGUREDATE"},
        ],
        compare_fields=[{"source_field": "QTY", "target_field": "QTY"}],
        source_schema=["PRDID", "LOCID", "KEYFIGUREDATE", "QTY"],
        target_schema=["PRDID", "LOCID", "KEYFIGUREDATE", "QTY"],
    )
    base.update(over)
    return TransformationContract(**base)


def test_iso_source_dates_join_against_slash_formatted_target_dates():
    contract = _contract()
    shadow = pd.DataFrame({
        "PRDID": ["15033625", "20039230"],
        "LOCID": ["6610", "6610"],
        "KEYFIGUREDATE": ["2026-09-04", "2026-09-14"],
        "QTY": [20, 1],
    })
    target = pd.DataFrame({
        "PRDID": ["15033625", "20039230"],
        "LOCID": ["6610", "6610"],
        "KEYFIGUREDATE": ["9/4/2026", "9/14/2026"],
        "QTY": [20, 1],
    })
    result = reconcile(contract, shadow, target)
    assert result.summary.match == 2
    assert result.summary.quantity_mismatch == 0
    assert result.summary.missing_in_target == 0
    assert result.summary.extra_in_target == 0


def test_float_artifact_prdid_joins_against_plain_text_prdid():
    contract = _contract()
    shadow = pd.DataFrame({
        "PRDID": [786293.0, 20041855.0],  # Excel-numeric-column artifact
        "LOCID": ["3340", "3300"],
        "KEYFIGUREDATE": ["2026-09-04", "2026-09-04"],
        "QTY": [5, 114],
    })
    target = pd.DataFrame({
        "PRDID": ["786293", "20041855"],  # plain text, no trailing ".0"
        "LOCID": ["3340", "3300"],
        "KEYFIGUREDATE": ["9/4/2026", "9/4/2026"],
        "QTY": [5, 114],
    })
    result = reconcile(contract, shadow, target)
    assert result.summary.match == 2
    assert result.summary.quantity_mismatch == 0


def test_alpha_suffixed_material_still_requires_an_exact_text_match():
    """A material code that ISN'T purely numeric (a real SAP convention —
    e.g. "15067451R") must still join on its literal text: canonicalization
    must never coerce it into something else or accidentally match it
    against an unrelated numeric code."""
    contract = _contract()
    shadow = pd.DataFrame({
        "PRDID": ["15067451R"],
        "LOCID": ["6610"],
        "KEYFIGUREDATE": ["2026-09-04"],
        "QTY": [1],
    })
    target_match = pd.DataFrame({
        "PRDID": ["15067451R"],
        "LOCID": ["6610"],
        "KEYFIGUREDATE": ["9/4/2026"],
        "QTY": [1],
    })
    target_no_match = pd.DataFrame({
        "PRDID": ["15067451"],  # different code, suffix dropped
        "LOCID": ["6610"],
        "KEYFIGUREDATE": ["9/4/2026"],
        "QTY": [1],
    })
    assert reconcile(contract, shadow, target_match).summary.match == 1
    result = reconcile(contract, shadow, target_no_match)
    assert result.summary.match == 0
    assert result.summary.extra_in_target == 1
    assert result.summary.missing_in_target == 1


def test_genuine_quantity_mismatch_still_surfaces_after_key_normalization():
    """Fixing the key join must not paper over a real compare-field
    discrepancy — a matched key with a different QTY is still a mismatch."""
    contract = _contract()
    shadow = pd.DataFrame({
        "PRDID": [786293.0], "LOCID": ["3340"], "KEYFIGUREDATE": ["2026-09-04"], "QTY": [5],
    })
    target = pd.DataFrame({
        "PRDID": ["786293"], "LOCID": ["3340"], "KEYFIGUREDATE": ["9/4/2026"], "QTY": [9],
    })
    result = reconcile(contract, shadow, target)
    assert result.summary.match == 0
    assert result.summary.quantity_mismatch == 1
