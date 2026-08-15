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
    # Rows the Value Mapping stage held out before the join ever ran (a
    # business-key field landed on a MEDIUM/NONE/OUT_OF_SCOPE match, or had no
    # match record at all) — never reconciled, so kept isolated from the three
    # classifications above and excluded from ``total``. Not a `RecordClass`:
    # these rows never reached the join. Keyed by SOURCE business-key field
    # name — any number of fields, not just two named ones.
    excluded_unmapped: dict[str, int] = Field(default_factory=dict)

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
        # Summaries persisted before excluded_unmapped became a generic
        # per-field dict carried two fixed named counters (Material/Plant
        # only) — migrated into the dict form on load.
        if "excluded_material_unmapped" in data or "excluded_plant_unmapped" in data:
            material = data.pop("excluded_material_unmapped", None)
            plant = data.pop("excluded_plant_unmapped", None)
            legacy: dict[str, int] = {}
            if material:
                legacy["Material"] = material
            if plant:
                legacy["ProductionPlant"] = plant
            data.setdefault("excluded_unmapped", legacy)
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


def excluded_unmapped_counts(held_out: list[dict[str, Any]]) -> dict[str, int]:
    """Sum held-out row counts per SOURCE business-key field name.

    ``held_out`` is :attr:`~engine.executor.ShadowBuildResult.held_out` —
    every row whose business-key field landed on a MEDIUM/NONE/OUT_OF_SCOPE
    match (or had no match record, or was blank) before the join ever ran.
    ``engine.executor._apply_value_mappings`` stamps ``held_out[i]["field"]``
    generically for ANY business-key field, so this sums across every field
    that actually held out rows — not just two named ones.
    """
    counts: dict[str, int] = {}
    for h in held_out:
        field = h.get("field")
        if not field:
            continue
        counts[field] = counts.get(field, 0) + int(h.get("row_count") or 0)
    return counts


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
