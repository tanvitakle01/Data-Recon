"""Deterministic (uuid5) vs random (uuid7) identity primitives — see
``recon_engine.ids``. The deterministic half is the load-bearing contract:
the same logical mapping/pair must resolve to the identical id in every run,
including when values differ only in case/whitespace, but a genuinely
different role (source vs. target swapped) must NOT collide.
"""

from __future__ import annotations

import uuid

from backend.recon_engine import ids


def test_new_id_is_a_valid_uuid7_and_unique():
    a, b = ids.new_id(), ids.new_id()
    assert a != b
    assert uuid.UUID(a).version == 7
    assert uuid.UUID(b).version == 7


def test_field_mapping_id_is_stable_across_calls():
    a = ids.field_mapping_id("s4", "ibp", "auto", "Material", "PRDID")
    b = ids.field_mapping_id("s4", "ibp", "auto", "Material", "PRDID")
    assert a == b
    assert uuid.UUID(a).version == 5


def test_field_mapping_id_normalizes_case_and_whitespace():
    a = ids.field_mapping_id("s4", "ibp", "auto", "Material", "PRDID")
    b = ids.field_mapping_id(" S4 ", " IBP ", " AUTO ", " material ", " prdid ")
    assert a == b


def test_field_mapping_id_is_order_sensitive():
    """Source and target are fixed roles, never interchangeable — unlike
    canonical_column_key's order-independent column SET."""
    forward = ids.field_mapping_id("s4", "ibp", "auto", "Material", "PRDID")
    swapped = ids.field_mapping_id("ibp", "s4", "auto", "PRDID", "Material")
    assert forward != swapped


def test_field_mapping_id_differs_for_different_fields():
    a = ids.field_mapping_id("s4", "ibp", "auto", "Material", "PRDID")
    b = ids.field_mapping_id("s4", "ibp", "auto", "Plant", "LOCID")
    assert a != b


def test_pair_id_is_stable_across_calls_and_batches():
    """The core dedup contract: the same (field_mapping_id, source_value,
    target_value) yields an IDENTICAL pair_id regardless of which batch or
    run discovered it, and regardless of value case/whitespace."""
    fm_id = ids.field_mapping_id("s4", "ibp", "auto", "Material", "PRDID")
    a = ids.pair_id(fm_id, "ABC123", "XYZ789")
    b = ids.pair_id(fm_id, " abc123 ", " xyz789 ")
    assert a == b
    assert uuid.UUID(a).version == 5


def test_pair_id_differs_for_different_field_mappings():
    fm1 = ids.field_mapping_id("s4", "ibp", "auto", "Material", "PRDID")
    fm2 = ids.field_mapping_id("s4", "ibp", "auto", "Plant", "LOCID")
    a = ids.pair_id(fm1, "ABC", "XYZ")
    b = ids.pair_id(fm2, "ABC", "XYZ")
    assert a != b


def test_pair_id_handles_none_target_value():
    fm_id = ids.field_mapping_id("s4", "ibp", "auto", "Material", "PRDID")
    # A NONE-confidence match has no target_value — must not raise.
    result = ids.pair_id(fm_id, "ABC", None)
    assert uuid.UUID(result).version == 5
