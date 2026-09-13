"""Deterministic reconciliation engine (no LLM at runtime).

* ``executor``         — applies an approved contract to Raw_Source -> Shadow_Source.
* ``reconciler``       — full outer join Shadow_Source vs Raw_Target -> classified results.
* ``anchor_inference`` — recovers a run's date anchor from a frozen target extract.
"""

from backend.recon_engine.engine.anchor_inference import AnchorInference, infer_anchor_date
from backend.recon_engine.engine.executor import (
    LINEAGE_COL,
    ShadowBuildResult,
    build_shadow_source,
    shadow_fingerprint,
)
from backend.recon_engine.engine.reconciler import ReconcileResult, reconcile

__all__ = [
    "AnchorInference",
    "LINEAGE_COL",
    "ReconcileResult",
    "ShadowBuildResult",
    "build_shadow_source",
    "infer_anchor_date",
    "reconcile",
    "shadow_fingerprint",
]
