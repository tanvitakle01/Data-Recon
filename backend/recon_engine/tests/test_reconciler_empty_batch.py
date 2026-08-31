"""``reconciler.reconcile`` must return a properly-shaped (0-row, correctly-
named) ``detail_df`` even when a batch resolves zero records — never the bare
``pd.DataFrame([])`` that has 0 rows AND 0 columns (see ``storage.frames.
append_frame``'s docstring on why a 0-column frame is dangerous once it's
appended to a streaming result file).
"""

from __future__ import annotations

import pandas as pd

from backend.recon_engine.engine.reconciler import _DETAIL_COLUMNS, reconcile
from backend.recon_engine.models.contract import TransformationContract


def _empty_contract() -> TransformationContract:
    return TransformationContract.model_validate(
        {
            "contract_id": "c1", "contract_version": 1,
            "source_type": "excel", "target_type": "excel", "comparison_type": "c",
            "business_key": [{"source_field": "k", "target_field": "k"}],
            "compare_fields": [],
        }
    )


def test_reconcile_gives_zero_records_the_canonical_columns_not_a_bare_empty_frame():
    contract = _empty_contract()
    empty = pd.DataFrame({"k": []})

    result = reconcile(contract, empty, empty)

    assert result.detail_df.empty
    assert result.detail_df.columns.tolist() == _DETAIL_COLUMNS
