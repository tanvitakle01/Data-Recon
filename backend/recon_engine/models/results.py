"""Reconciliation result classifications and summary."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RecordClass(str, Enum):
    """The four terminal classifications after the full outer join."""

    MATCH = "match"
    MISMATCH = "mismatch"
    MISSING_IN_SOURCE = "missing_in_source"
    MISSING_IN_TARGET = "missing_in_target"


class ReconciliationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int = 0
    match: int = 0
    # Field-level compare failure on a key present on both sides (was called
    # ``mismatch`` before the bucket below was introduced).
    quantity_mismatch: int = 0
    # Everything that is not a match and not a quantity mismatch — i.e. every
    # record whose business key exists on only one side. Not a sum of two
    # named sub-categories; it is simply ``total - match - quantity_mismatch``.
    # There is no user-facing "missing in target" / "extra in target" split.
    mismatch: int = 0
    # Rows the Value Mapping stage held out before the join ever ran (Material
    # or Plant landed on a MEDIUM/NONE/OUT_OF_SCOPE match, or had no match
    # record at all) — never reconciled, so kept isolated from the three
    # classifications above and excluded from ``total``. Not a `RecordClass`:
    # these rows never reached the join.
    excluded_material_unmapped: int = 0
    excluded_plant_unmapped: int = 0

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_buckets(cls, data: Any) -> Any:
        # Summaries persisted before the EXCEPTION classification was removed
        # still carry an ``exception`` count; ``extra="forbid"`` would reject
        # them, so strip the retired key when loading historical results.
        # Summaries persisted before missing_in_source/missing_in_target were
        # unified into one ``mismatch`` bucket (and the old field-level
        # ``mismatch`` was renamed ``quantity_mismatch``) are migrated the same
        # way on load.
        if not isinstance(data, dict):
            return data
        data = {k: v for k, v in data.items() if k != "exception"}
        if "missing_in_source" in data or "missing_in_target" in data:
            data.pop("missing_in_source", None)
            data.pop("missing_in_target", None)
            match = data.get("match", 0) or 0
            quantity_mismatch = data.pop("mismatch", 0) or 0
            total = data.get("total", 0) or 0
            data["quantity_mismatch"] = quantity_mismatch
            data["mismatch"] = total - match - quantity_mismatch
        return data

    @classmethod
    def from_counts(cls, counts: dict[str, int]) -> "ReconciliationSummary":
        total = sum(counts.values())
        match = counts.get(RecordClass.MATCH.value, 0)
        quantity_mismatch = counts.get(RecordClass.MISMATCH.value, 0)
        return cls(
            match=match,
            quantity_mismatch=quantity_mismatch,
            mismatch=total - match - quantity_mismatch,
            total=total,
        )


def excluded_unmapped_counts(held_out: list[dict[str, Any]]) -> tuple[int, int]:
    """Sum held-out row counts for the Material and Plant business-key fields.

    ``held_out`` is :attr:`~engine.executor.ShadowBuildResult.held_out` — every
    row whose Material or Plant landed on a MEDIUM/NONE/OUT_OF_SCOPE match (or
    had no match record, or was blank) before the join ever ran. Keyed on the
    literal SAP field names this app's two business-key fields always use
    (``Material`` -> PRDID, ``ProductionPlant`` -> LOCID).
    """
    material = sum(int(h.get("row_count") or 0) for h in held_out if h.get("field") == "Material")
    plant = sum(int(h.get("row_count") or 0) for h in held_out if h.get("field") == "ProductionPlant")
    return material, plant


class ReconciliationResult(BaseModel):
    """Persisted outcome of a run. Detail rows live on disk at ``storage_path``."""

    model_config = ConfigDict(extra="forbid")

    result_id: str
    run_id: str
    contract_id: str
    contract_version: int

    summary: ReconciliationSummary
    storage_path: str
    created_at: datetime = Field(default_factory=_utcnow)
