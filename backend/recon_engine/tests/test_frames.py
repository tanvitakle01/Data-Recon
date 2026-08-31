"""Coverage for ``storage.frames``' JSON-Lines append/read pair — specifically
the "0 columns passed, passed data had N columns" bug: an empty (0-row, and
therefore 0-column — see ``pd.DataFrame([])``) batch frame writing the FIRST
line of a result file locked in an empty ``columns`` header forever, silently
corrupting every later batch's real rows appended under it. See
``append_frame``'s docstring for the full mechanism.
"""

from __future__ import annotations

import pandas as pd

from backend.recon_engine.storage import frames


def test_append_frame_is_a_no_op_for_an_empty_frame(tmp_path):
    path = tmp_path / "result.jsonl"
    frames.append_frame(pd.DataFrame(), path)
    assert not path.exists()


def test_append_frame_is_a_no_op_for_an_empty_but_columned_frame(tmp_path):
    """Even an empty frame that DOES carry real column names (the
    ``reconciler.py`` fix's shape) must not define the file's header — only a
    frame with actual rows should."""
    path = tmp_path / "result.jsonl"
    frames.append_frame(pd.DataFrame(columns=["a", "b"]), path)
    assert not path.exists()


def test_an_empty_batch_before_a_real_one_no_longer_corrupts_the_header(tmp_path):
    path = tmp_path / "result.jsonl"
    frames.append_frame(pd.DataFrame(), path)  # the pathological empty-first-batch case
    frames.append_frame(pd.DataFrame({"a": [1], "b": [2]}), path)
    frames.append_frame(pd.DataFrame({"a": [3], "b": [4]}), path)

    df = frames.read_frame_jsonl(path)
    assert df.columns.tolist() == ["a", "b"]
    assert df["a"].tolist() == [1, 3]
    assert df["b"].tolist() == [2, 4]


def test_read_frame_jsonl_returns_empty_frame_when_every_batch_was_empty(tmp_path):
    path = tmp_path / "result.jsonl"
    frames.append_frame(pd.DataFrame(), path)
    frames.append_frame(pd.DataFrame(columns=["a", "b"]), path)
    assert frames.read_frame_jsonl(path).empty
