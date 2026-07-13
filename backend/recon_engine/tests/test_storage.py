from __future__ import annotations

import pandas as pd

from backend.recon_engine.models.snapshot import RawLayer
from backend.recon_engine.storage import frames, shadow_store, snapshot_store


def test_snapshot_is_immutable_and_reproducible():
    df = pd.DataFrame({"id": ["a", "b"], "qty": [1, 2]})
    snap = snapshot_store.create_snapshot(df, layer=RawLayer.SOURCE, source_type="excel")

    fetched = snapshot_store.get_snapshot(snap.snapshot_id)
    assert fetched is not None
    assert fetched.snapshot_hash == snap.snapshot_hash

    loaded = snapshot_store.load_snapshot_frame(snap.snapshot_id)
    assert loaded["id"].tolist() == ["a", "b"]
    # Same data -> same hash (reproducibility).
    assert frames.compute_frame_hash(loaded) == snap.snapshot_hash


def test_snapshot_store_exposes_no_mutation_api():
    # Immutability is enforced structurally: no update/delete entry points.
    assert not hasattr(snapshot_store, "update_snapshot")
    assert not hasattr(snapshot_store, "delete_snapshot")


def test_distinct_data_yields_distinct_hash():
    h1 = frames.compute_frame_hash(pd.DataFrame({"a": [1]}))
    h2 = frames.compute_frame_hash(pd.DataFrame({"a": [2]}))
    assert h1 != h2


def test_shadow_ttl_cleanup_removes_expired():
    df = pd.DataFrame({"id": ["a"], "qty": [1]})
    # Negative TTL -> already expired.
    shadow = shadow_store.create_shadow(
        df, run_id="r1", contract_id="c1", contract_version=1,
        raw_snapshot_id="snap1", raw_snapshot_hash="h", ttl_days=-1,
    )
    removed = shadow_store.cleanup_expired()
    assert shadow.shadow_id in removed
    assert shadow_store.get_shadow(shadow.shadow_id) is None


def test_shadow_not_expired_is_retained():
    df = pd.DataFrame({"id": ["a"], "qty": [1]})
    shadow = shadow_store.create_shadow(
        df, run_id="r2", contract_id="c1", contract_version=1,
        raw_snapshot_id="snap1", raw_snapshot_hash="h", ttl_days=7,
    )
    removed = shadow_store.cleanup_expired()
    assert shadow.shadow_id not in removed
    assert shadow_store.get_shadow(shadow.shadow_id) is not None
