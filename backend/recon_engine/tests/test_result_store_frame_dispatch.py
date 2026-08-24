"""``result_store.load_result_frame_any`` — dispatches to the right reader for
either writer (:func:`save_result`'s single-blob JSON vs.
:func:`start_streaming_result`/:func:`append_batch_result`'s JSON-Lines),
so a caller that only has a bare ``result_id`` (``service.build_enriched_detail``,
the shared ``GET /api/recon/results/{id}`` route) doesn't need to know which
one wrote it. Reading a streaming ``.jsonl`` result through the single-blob
reader raises (that JSON-Lines format isn't one JSON document) — the bug this
guards against.
"""

from __future__ import annotations

import pandas as pd

from backend.recon_engine.models.results import ReconciliationSummary
from backend.recon_engine.storage import result_store


def test_load_result_frame_any_reads_a_single_blob_result():
    result = result_store.save_result(
        run_id="run-1", contract_id="c1", contract_version=1,
        summary=ReconciliationSummary(total=1, match=1),
        detail_df=pd.DataFrame({"business_key": ["a"], "classification": ["match"]}),
    )
    df = result_store.load_result_frame_any(result.result_id)
    assert df["business_key"].tolist() == ["a"]


def test_load_result_frame_any_reads_a_streaming_jsonl_result():
    result = result_store.start_streaming_result(run_id="run-2", contract_id="c1", contract_version=1)
    result_store.append_batch_result(
        result.result_id,
        detail_df=pd.DataFrame({"business_key": ["b"], "classification": ["mismatch"]}),
        batch_summary=ReconciliationSummary(total=1, mismatch=1),
    )
    assert result.storage_path.endswith(".jsonl")

    df = result_store.load_result_frame_any(result.result_id)
    assert df["business_key"].tolist() == ["b"]


def test_load_result_frame_raises_on_a_streaming_result_unlike_load_result_frame_any():
    """The bug :func:`load_result_frame_any` exists to route around: the
    single-blob reader can't parse a JSON-Lines file."""
    import pytest

    result = result_store.start_streaming_result(run_id="run-3", contract_id="c1", contract_version=1)
    result_store.append_batch_result(
        result.result_id,
        detail_df=pd.DataFrame({"business_key": ["c"], "classification": ["match"]}),
        batch_summary=ReconciliationSummary(total=1, match=1),
    )
    with pytest.raises(Exception):
        result_store.load_result_frame(result.result_id)
