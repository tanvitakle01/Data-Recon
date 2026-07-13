"""The Transformation Contract — the single executable specification.

A contract is *data*, never code. It references operations from the
allow-listed registry by name and supplies parameters for each. The
deterministic engine is the only thing that turns a contract into execution.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ApprovalStatus(str, Enum):
    """Lifecycle of a contract. Only ``APPROVED`` contracts may be executed."""

    DRAFT = "draft"
    VALIDATED = "validated"  # passed both gates, awaiting human approval
    APPROVED = "approved"
    REJECTED = "rejected"


class MatchType(str, Enum):
    EXACT = "exact"
    TOLERANCE = "tolerance"


class AggregationType(str, Enum):
    """How a source field is aggregated before reconciliation.

    Split into two families used differently by the engine:
      * MEASURE (sum/count/average/min/max) — aggregate a numeric field within
        each group.
      * PERIOD (group_by_*) — bucket a date field to a coarser granularity so it
        becomes a grouping dimension (the bucket start date is emitted).
    """

    SUM = "sum"
    COUNT = "count"
    AVERAGE = "average"
    MIN = "min"
    MAX = "max"
    GROUP_BY_DAY = "group_by_day"
    GROUP_BY_WEEK = "group_by_week"
    GROUP_BY_MONTH = "group_by_month"
    GROUP_BY_QUARTER = "group_by_quarter"
    GROUP_BY_YEAR = "group_by_year"


# Aggregation families — imported by the executor/validation to branch on intent.
PERIOD_AGGREGATIONS: frozenset[AggregationType] = frozenset({
    AggregationType.GROUP_BY_DAY,
    AggregationType.GROUP_BY_WEEK,
    AggregationType.GROUP_BY_MONTH,
    AggregationType.GROUP_BY_QUARTER,
    AggregationType.GROUP_BY_YEAR,
})
MEASURE_AGGREGATIONS: frozenset[AggregationType] = frozenset({
    AggregationType.SUM,
    AggregationType.COUNT,
    AggregationType.AVERAGE,
    AggregationType.MIN,
    AggregationType.MAX,
})


class AggregationRule(BaseModel):
    """One aggregation directive: aggregate/group ``source_field`` by ``aggregation``.

    Collected as structured user input (never free text) and applied
    deterministically by the engine during the Aggregation stage.
    """

    model_config = ConfigDict(extra="forbid")

    source_field: str
    aggregation: AggregationType


class ContractOperation(BaseModel):
    """A single allow-listed operation reference.

    Deliberately generic: ``op`` must name an operation in the registry, and
    ``params`` are validated against that operation's declared schema during
    Gate 1. There is intentionally no field for code, expressions, or scripts.
    """

    model_config = ConfigDict(extra="forbid")

    op: str = Field(..., description="Registry operation name (must be allow-listed).")
    field: str | None = Field(
        default=None, description="Column the operation acts on (if applicable)."
    )
    params: dict[str, Any] = Field(default_factory=dict)


class BusinessKeyField(BaseModel):
    """One component of the composite business key used for the join."""

    model_config = ConfigDict(extra="forbid")

    source_field: str
    target_field: str


class CompareField(BaseModel):
    """A field compared between shadow source and raw target after the join."""

    model_config = ConfigDict(extra="forbid")

    source_field: str
    target_field: str
    match_type: MatchType = MatchType.EXACT
    # Absolute tolerance for numeric comparison when match_type == TOLERANCE.
    tolerance: float | None = None


class ContractBody(BaseModel):
    """Fields shared by draft and approved contracts.

    This is also the exact shape a :class:`~backend.recon_engine.compiler.base.ContractCompiler`
    is responsible for producing. ``DraftContract`` and ``TransformationContract``
    add server-owned provenance fields (``created_at``, ``created_by``,
    ``compiler``, ``approval_status``, ...) on top of this — a compiler must
    never set those itself, so its output schema/validation should be scoped
    to ``ContractBody``, not the full subclass.
    """

    model_config = ConfigDict(extra="forbid")

    comparison_type: str = Field(..., description="e.g. 'sales_history', 'salesorderhistory'.")
    source_type: str = Field(..., description="e.g. 'excel', 's4'.")
    target_type: str = Field(..., description="e.g. 'excel', 'ibp'.")

    # Operations applied to Raw_Source to derive the Shadow_Source. The engine
    # runs them in a fixed pipeline (Filters → Transformations → Aggregations),
    # preserving each op's relative order within its stage.
    operations: list[ContractOperation] = Field(default_factory=list)

    # Structured aggregations applied in the Aggregation stage (after filters and
    # transforms). Compiled from the UI's Aggregation Rules, not free text.
    aggregation_rules: list[AggregationRule] = Field(default_factory=list)

    business_key: list[BusinessKeyField] = Field(default_factory=list)
    compare_fields: list[CompareField] = Field(default_factory=list)

    # Schemas captured at compile time from the real sources (S/4, IBP, upload)
    # so Gate 1 can validate field references without assuming any fields.
    source_schema: list[str] = Field(default_factory=list)
    target_schema: list[str] = Field(default_factory=list)

    options: dict[str, Any] = Field(
        default_factory=lambda: {"case_insensitive": True, "trim_whitespace": True}
    )
    notes: str | None = None


class DraftContract(ContractBody):
    """A freshly compiled contract, before validation/approval.

    Produced by a :class:`~backend.recon_engine.compiler.base.ContractCompiler`.
    Carries no identity/version yet — those are assigned on approval.
    """

    approval_status: ApprovalStatus = ApprovalStatus.DRAFT
    created_at: datetime = Field(default_factory=_utcnow)
    created_by: str = "system"
    # Provenance of the draft: which compiler produced it (e.g. "groq", "stub").
    compiler: str = "unknown"


class TransformationContract(ContractBody):
    """A persisted, versioned contract.

    An APPROVED instance is the only artifact the runtime engine will execute.
    """

    contract_id: str
    contract_version: int = Field(..., ge=1)
    created_at: datetime = Field(default_factory=_utcnow)
    created_by: str = "system"
    compiler: str = "unknown"

    approval_status: ApprovalStatus = ApprovalStatus.DRAFT
    approved_by: str | None = None
    approved_at: datetime | None = None

    def is_executable(self) -> bool:
        return self.approval_status == ApprovalStatus.APPROVED
