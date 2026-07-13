"""Deterministic reconciliation engine (no LLM at runtime).

* ``executor``   — applies an approved contract to Raw_Source -> Shadow_Source.
* ``reconciler`` — full outer join Shadow_Source vs Raw_Target -> classified results.
"""

from backend.recon_engine.engine.executor import (
    LINEAGE_COL,
    ShadowBuildResult,
    build_shadow_source,
    shadow_fingerprint,
)
from backend.recon_engine.engine.reconciler import ReconcileResult, reconcile

__all__ = [
    "LINEAGE_COL",
    "ReconcileResult",
    "ShadowBuildResult",
    "build_shadow_source",
    "reconcile",
    "shadow_fingerprint",
]
