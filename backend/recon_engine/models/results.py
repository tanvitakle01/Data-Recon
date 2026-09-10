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
    # Business key present in source only (absent from target) vs. present in
    # target only (absent from source) — the two one-sided cases, shown to
    # users as "Missing in Target" / "Extra in Target" respectively.
    missing_in_target: int = 0
    extra_in_target: int = 0
    # Kept for backward compatibility with older persisted summaries and any
    # code still reading the umbrella count; always
    # ``missing_in_target + extra_in_target`` going forward.
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
        #
        # Two older summary shapes to migrate on load, oldest first below:
        # the original one-sided split (``missing_in_source``/
        # ``missing_in_target``), and the later unified single ``mismatch``
        # bucket that had no split at all (best effort then puts the whole
        # total under ``missing_in_target`` rather than inventing a 50/50
        # guess). A dict from a fresh ``from_counts()`` call always supplies
        # ``missing_in_target``/``extra_in_target`` explicitly and matches
        # neither branch.
        if not isinstance(data, dict):
            return data
        data = {k: v for k, v in data.items() if k != "exception"}
        if "missing_in_source" in data:
            # Oldest format: had the one-sided split already, named
            # ``missing_in_source``/``missing_in_target`` directly —
            # ``missing_in_source`` (target-only) is today's ``extra_in_target``.
            # (``missing_in_source`` never appears in the current schema, so
            # its presence alone is what identifies this format — unlike
            # ``missing_in_target``, which is also today's live field name.)
            extra_in_target = data.pop("missing_in_source", 0) or 0
            missing_in_target = data.get("missing_in_target", 0) or 0
            quantity_mismatch = data.pop("mismatch", 0) or 0
            data["quantity_mismatch"] = quantity_mismatch
            data["missing_in_target"] = missing_in_target
            data["extra_in_target"] = extra_in_target
            data["mismatch"] = missing_in_target + extra_in_target
        elif "mismatch" in data and "extra_in_target" not in data and "missing_in_target" not in data:
            # Unified format: only the combined count survived, with no
            # ``missing_in_target``/``extra_in_target`` fields at all (unlike
            # a fresh ``from_counts()`` construction, which always supplies
            # both).
            data["missing_in_target"] = data.get("mismatch", 0) or 0
            data["extra_in_target"] = 0
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
        missing_in_target = counts.get(RecordClass.MISSING_IN_TARGET.value, 0)
        extra_in_target = counts.get(RecordClass.MISSING_IN_SOURCE.value, 0)
        return cls(
            match=match,
            quantity_mismatch=quantity_mismatch,
            missing_in_target=missing_in_target,
            extra_in_target=extra_in_target,
            mismatch=missing_in_target + extra_in_target,
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
