"""Pydantic models for the reconciliation engine.

These models are the *only* legal shapes for data crossing subsystem
boundaries. In particular, a :class:`TransformationContract` is the single
executable specification produced by the compile phase and consumed by the
deterministic engine — the LLM may emit nothing else.
"""

from backend.recon_engine.models.audit import AuditAction, AuditEvent
from backend.recon_engine.models.contract import (
    ApprovalStatus,
    BusinessKeyField,
    CompareField,
    ContractOperation,
    DraftContract,
    MatchType,
    TransformationContract,
)
from backend.recon_engine.models.results import (
    RecordClass,
    ReconciliationResult,
    ReconciliationSummary,
)
from backend.recon_engine.models.run import ReconciliationRun, RunStatus, ShadowSource
from backend.recon_engine.models.snapshot import RawLayer, RawSnapshot
from backend.recon_engine.models.value_mapping import Confidence, ValueMapping, ValueMatch

__all__ = [
    "ApprovalStatus",
    "AuditAction",
    "AuditEvent",
    "BusinessKeyField",
    "CompareField",
    "Confidence",
    "ContractOperation",
    "DraftContract",
    "MatchType",
    "RawLayer",
    "RawSnapshot",
    "RecordClass",
    "ReconciliationResult",
    "ReconciliationRun",
    "ReconciliationSummary",
    "RunStatus",
    "ShadowSource",
    "TransformationContract",
    "ValueMapping",
    "ValueMatch",
]
