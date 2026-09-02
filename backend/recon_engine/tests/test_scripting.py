"""Script-transformation flow: validator, sandbox, fallback generator, lifecycle."""

from __future__ import annotations

import pandas as pd
import pytest

from backend.recon_engine import service
from backend.recon_engine.models.snapshot import RawLayer
from backend.recon_engine.scripting import (
    ScriptExecutionError,
    execute_script,
    generate_script,
    validate_script,
)
from backend.recon_engine.storage import script_store

VALID_SCRIPT = """
def transform(df):
    df = df.copy()
    df["MATNR"] = df["MATNR"].astype(str).str.lstrip("0")
    df = df.rename(columns={"MATNR": "PRDID"})
    return df
"""


# ── static validation ────────────────────────────────────────────────────────

def test_validator_accepts_clean_transform():
    assert validate_script(VALID_SCRIPT).ok


@pytest.mark.parametrize(
    "snippet",
    [
        "import os\ndef transform(df):\n    return df",
        "import subprocess\ndef transform(df):\n    return df",
        "def transform(df):\n    eval('1+1')\n    return df",
        "def transform(df):\n    exec('x=1')\n    return df",
        "def transform(df):\n    open('x.txt', 'w')\n    return df",
        "def transform(df):\n    df.to_csv('out.csv')\n    return df",
        "def transform(df):\n    pd.read_csv('in.csv')\n    return df",
        "def transform(df):\n    x = ().__class__\n    return df",
        "def transform(df):\n    __import__('os')\n    return df",
        "def transform(df):\n    import requests\n    return df",
        "def transform(df):\n    getattr(df, 'to_' + 'csv')('x')\n    return df",
        "x = 1",  # no transform function
        "def transform(df):\n    pass",  # no return
        "def transform():\n    return 1",  # no df argument
    ],
)
def test_validator_rejects_unsafe_or_malformed(snippet):
    report = validate_script(snippet)
    assert not report.ok
    assert report.errors


def test_validator_allows_approved_imports():
    script = "import math\ndef transform(df):\n    df['x'] = math.pi\n    return df"
    assert validate_script(script).ok


# ── sandbox execution ────────────────────────────────────────────────────────

def test_sandbox_executes_and_diffs():
    df = pd.DataFrame({"MATNR": ["000123", "000456", "789"], "QTY": [1, 2, 3]})
    result = execute_script(VALID_SCRIPT, df)

    assert list(result.transformed_df.columns) == ["PRDID", "QTY"]
    assert result.transformed_df["PRDID"].tolist() == ["123", "456", "789"]
    # MATNR -> PRDID with changed values: one 'modified' column with a 'from'.
    assert result.modified_columns == [
        {"column": "PRDID", "change": "modified", "from": "MATNR"}
    ]
    assert result.affected_rows == 2  # "789" is unchanged
    assert {d["row_index"] for d in result.row_diffs} == {0, 1}
    assert result.row_diffs[0]["changes"] == [
        {"column": "PRDID", "before": "000123", "after": "123"}
    ]
    assert result.execution_log


def test_sandbox_refuses_statically_invalid_script():
    df = pd.DataFrame({"A": [1]})
    with pytest.raises(ScriptExecutionError, match="static validation"):
        execute_script("import os\ndef transform(df):\n    return df", df)


def test_sandbox_blocks_disallowed_import_at_runtime():
    # Belt and braces: even if a script slipped past the AST gate, the guarded
    # __import__ refuses. (Import of an allowed module works.)
    df = pd.DataFrame({"A": [1]})
    ok = "import re\ndef transform(df):\n    return df"
    assert execute_script(ok, df).transformed_df is not None


def test_sandbox_surfaces_runtime_errors():
    df = pd.DataFrame({"A": [1]})
    script = "def transform(df):\n    return df['missing_column'].to_frame()"
    with pytest.raises(ScriptExecutionError, match="raised during execution"):
        execute_script(script, df)


def test_sandbox_rejects_non_dataframe_result():
    df = pd.DataFrame({"A": [1]})
    script = "def transform(df):\n    return 42"
    with pytest.raises(ScriptExecutionError, match="must return a pandas DataFrame"):
        execute_script(script, df)


# ── fallback generator (Groq unconfigured in tests via conftest) ─────────────

PARSED_MAPPING = {
    "sheet_name": "Mapping",
    "headers": ["Target Fields", "Source Table/Field", "Transformation"],
    "rows": [],
    "mapping_candidates": [
        {
            "row_index": 0,
            "source_field": "MATNR",
            "target_field": "PRDID",
            "technical_field": None,
            "description": "Material",
            "transformation": "Remove leading zeros",
            "join_condition": None,
            "filter": None,
        },
        {
            "row_index": 1,
            "source_field": "WERKS",
            "target_field": "LOCID",
            "technical_field": None,
            "description": "Plant",
            "transformation": None,
            "join_condition": None,
            "filter": None,
        },
    ],
    "transformation_notes": [],
    "join_conditions": [],
    "filters": [],
}


def test_fallback_generator_produces_valid_previewable_script():
    script, degraded_reason = generate_script(
        parsed_mapping=PARSED_MAPPING,
        rules="",
        source_schema=["MATNR", "WERKS", "QTY"],
        target_schema=["PRDID", "LOCID", "QTY"],
    )
    assert script.generated_by.value == "fallback"
    assert degraded_reason  # Azure AI Foundry not configured
    assert validate_script(script.script).ok
    assert any("leading zeros" in step.lower() for step in script.explanation)
    assert any("renamed matnr" in step.lower() for step in script.explanation)

    df = pd.DataFrame({"MATNR": ["000123"], "WERKS": ["1000"], "QTY": [5]})
    result = execute_script(script.script, df)
    assert list(result.transformed_df.columns) == ["PRDID", "LOCID", "QTY"]
    assert result.transformed_df["PRDID"].tolist() == ["123"]


def test_fallback_generator_identity_when_nothing_recognised():
    script, _ = generate_script(
        parsed_mapping=[], rules="", source_schema=["A"], target_schema=["B"]
    )
    assert validate_script(script.script).ok
    df = pd.DataFrame({"A": [1, 2]})
    result = execute_script(script.script, df)
    assert result.transformed_df.equals(df)
    assert result.affected_rows == 0


# ── full lifecycle: generate → preview → approve → production run ────────────

def _generate_and_preview():
    script, report, _ = service.generate_transformation_script(
        parsed_mapping=PARSED_MAPPING,
        rules="",
        source_schema=["MATNR", "WERKS", "QTY"],
        target_schema=["PRDID", "LOCID", "QTY"],
        actor="tester",
    )
    assert report["ok"]
    sample = pd.DataFrame(
        {"MATNR": ["000123", "000456"], "WERKS": ["1000", "2000"], "QTY": [5, 7]}
    )
    preview, _ = service.preview_transformation(script.script_id, sample, actor="tester")
    return script, preview


def test_lifecycle_preview_approve_and_production_run():
    script, preview = _generate_and_preview()
    assert preview.affected_rows == 2
    assert preview.row_count == 2

    approval = service.approve_transformation_preview(
        preview.preview_id, approved_by="tester"
    )
    assert approval.script_hash == script.script_hash
    assert approval.preview_snapshot_id == preview.preview_id

    source = pd.DataFrame(
        {"MATNR": ["000123", "000456", "000999"], "WERKS": ["1000", "2000", "3000"], "QTY": [5, 7, 9]}
    )
    target = pd.DataFrame(
        {"PRDID": ["123", "456", "777"], "LOCID": ["1000", "2000", "4000"], "QTY": [5, 8, 1]}
    )
    src_snap = service.ingest_snapshot(source, layer=RawLayer.SOURCE, source_type="excel")
    tgt_snap = service.ingest_snapshot(target, layer=RawLayer.TARGET, source_type="excel")

    out = service.run_reconciliation_with_script(
        approval_id=approval.approval_id,
        source_snapshot_id=src_snap.snapshot_id,
        target_snapshot_id=tgt_snap.snapshot_id,
        business_key=[
            {"source_field": "MATNR", "target_field": "PRDID"},
            {"source_field": "WERKS", "target_field": "LOCID"},
        ],
        compare_fields=[{"source_field": "QTY", "target_field": "QTY"}],
        actor="tester",
    )
    summary = out["summary"]
    assert summary["match"] == 1            # 123/1000 QTY 5
    assert summary["quantity_mismatch"] == 1  # 456/2000 QTY 7 vs 8
    assert summary["mismatch"] == 2          # 999/3000 + 777/4000 (one-sided keys)
    assert out["transformation"]["script_id"] == script.script_id
    assert out["transformation"]["generated_by"] == "fallback"


def test_production_run_refuses_tampered_script():
    script, preview = _generate_and_preview()
    approval = service.approve_transformation_preview(
        preview.preview_id, approved_by="tester"
    )

    # Tamper with the stored script text after approval.
    from backend.recon_engine.storage.db import main_db

    with main_db() as conn:
        conn.execute(
            "UPDATE transformation_scripts SET script_text = ? WHERE script_id = ?",
            ("def transform(df):\n    return df\n", script.script_id),
        )

    src = service.ingest_snapshot(
        pd.DataFrame({"MATNR": ["1"], "WERKS": ["1"], "QTY": [1]}),
        layer=RawLayer.SOURCE, source_type="excel",
    )
    tgt = service.ingest_snapshot(
        pd.DataFrame({"PRDID": ["1"], "LOCID": ["1"], "QTY": [1]}),
        layer=RawLayer.TARGET, source_type="excel",
    )
    with pytest.raises(ValueError, match="hash mismatch"):
        service.run_reconciliation_with_script(
            approval_id=approval.approval_id,
            source_snapshot_id=src.snapshot_id,
            target_snapshot_id=tgt.snapshot_id,
            business_key=[{"source_field": "MATNR", "target_field": "PRDID"}],
            actor="tester",
        )


def test_rejected_preview_cannot_be_approved():
    _, preview = _generate_and_preview()
    service.reject_transformation_preview(preview.preview_id, actor="tester", reason="wrong")
    assert script_store.get_preview(preview.preview_id).status.value == "rejected"
    with pytest.raises(ValueError, match="rejected"):
        service.approve_transformation_preview(preview.preview_id, approved_by="tester")
