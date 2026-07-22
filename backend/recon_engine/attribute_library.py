"""Three-tier generation glue for the attribute-mapping library.

Tier 1 (:func:`library_result_for`) — look the current source+target column set
up in the library; on a hit, build the SAME ``{display, mapping, ...}`` result
the LLM path returns, labeled as a library hit. Tier 2 (the LLM) is the caller's
job (``field_mapper.infer_field_mapping``); tier 3 (manual) is the editor UI.

Store-back (:func:`store_back_from_contract`) — after a run completes, upsert the
contract's FIELD mapping (business_key + compare_fields → column→column pairs)
into the library, keyed by the canonical column-set key. Field mapping only:
``value_mappings`` on the contract are deliberately NOT stored here.

The canonical key column universe is the full per-side dataset column set. On
store-back that is ``contract.source_schema`` / ``target_schema`` (captured at
compile from the real sources); on lookup it is the columns the infer route is
handed. The frontend sends the SAME ``source.dataset.columns`` to both the
compile endpoint (→ source_schema) and the infer endpoint (→ lookup), so the two
canonical keys agree and reuse actually happens.
"""

from __future__ import annotations

from typing import Any

from backend.recon_engine.field_mapper import (
    COMPARE_ROLE,
    KEY_ROLE,
    _DEFAULT_OPTIONS,
    _to_mapping,
)
from backend.recon_engine.models.attribute_mapping import AttributePair, MappingProvenance
from backend.recon_engine.models.audit import AuditAction
from backend.recon_engine.models.contract import TransformationContract
from backend.recon_engine.storage import attribute_mapping_store, audit_store


def _is_key(role: str) -> bool:
    return "key" in str(role or "").lower()


def library_result_for(
    *,
    source_connector: str,
    target_connector: str,
    comparison_type: str,
    source_columns: list[str],
    target_columns: list[str],
) -> dict[str, Any] | None:
    """Tier 1: return a mapping-card result from the library, or ``None``.

    On a hit the row's ``last_used_on`` is refreshed and every emitted row is
    tagged ``provenance="library"`` so the card renders "Generated via Vector
    Library". Returns ``None`` when nothing is stored for this exact key — the
    caller then falls through to the LLM.
    """
    hit = attribute_mapping_store.lookup(
        source_connector=source_connector,
        target_connector=target_connector,
        comparison_type=comparison_type,
        source_columns=source_columns,
        target_columns=target_columns,
    )
    if hit is None:
        return None

    attribute_mapping_store.touch_last_used(hit.id)

    display = [
        {
            "logical": "",
            "source_col": pair.source_col,
            "target_col": pair.target_col,
            "role": KEY_ROLE if _is_key(pair.role) else COMPARE_ROLE,
            "reason": pair.reason or "Reused from the Vector Library.",
            "provenance": "library",
        }
        for pair in hit.mappings
    ]
    return {
        "display": display,
        "mapping": _to_mapping(display),
        "unmapped": {"source": [], "target": []},
        "warnings": [],
        "degraded": False,
        "degraded_reason": None,
        "provider": None,
        "fallback": False,
        "provider_notice": "Reused a validated mapping from the Vector Library.",
        "source": "library",
        "library_id": hit.id,
        "library_version": hit.version,
        "confidence": hit.confidence,
    }


def store_back_from_contract(
    contract: TransformationContract,
    run_id: str,
    *,
    confidence: float | None = None,
    actor: str = "system",
):
    """Store-back: upsert the run's FIELD mapping into the library.

    Only the column→column pairings (keys + compares) are stored — value
    mappings stay with the deterministic matcher. No-op (returns ``None``) if the
    contract carried no field mapping, so un-run/empty drafts never pollute the
    library. Dedup + version bump are handled by ``attribute_mapping_store.upsert``.
    """
    pairs: list[AttributePair] = [
        AttributePair(source_col=bk.source_field, target_col=bk.target_field, role="key")
        for bk in contract.business_key
    ]
    pairs += [
        AttributePair(
            source_col=cf.source_field,
            target_col=cf.target_field,
            role="compare",
            reason=f"match_type={getattr(cf.match_type, 'value', cf.match_type)}",
        )
        for cf in contract.compare_fields
    ]
    if not pairs:
        return None

    mapping = attribute_mapping_store.upsert(
        source_connector=contract.source_type,
        target_connector=contract.target_type,
        comparison_type=contract.comparison_type,
        source_columns=list(contract.source_schema),
        target_columns=list(contract.target_schema),
        mappings=pairs,
        provenance=MappingProvenance.LIBRARY,
        confidence=confidence,
        added_by=actor,
        validated_by_run_id=run_id,
        details={
            "source_columns": list(contract.source_schema),
            "target_columns": list(contract.target_schema),
            "contract_id": contract.contract_id,
            "contract_version": contract.contract_version,
        },
    )
    audit_store.record(
        AuditAction.LIBRARY_MAPPING_STORED,
        entity_type="attribute_mapping",
        entity_id=mapping.id,
        actor=actor,
        details={"run_id": run_id, "version": mapping.version},
    )
    return mapping
