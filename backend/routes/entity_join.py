"""POST /api/recon/entity-join/parse — the free-text entity/join fallback.

Used when the mapping sheet doesn't state which entities to fetch or how to join
them (and as a deliberate override when it does). The endpoint loads the
connector's LIVE entity list server-side from ``kind``, which is what makes the
source/target boundary hold structurally: a ``kind="s4"`` request can only ever
see S/4 entities, ``kind="ibp"`` only IBP entities — one side's input can never
surface the other's entities.

The sheet path has no endpoint of its own: entities/join are additional output of
the existing ``/api/recon/mapping-sheet/identify`` call. Both paths share the one
gate in ``entity_join_parser.resolve_entity_join``.

This output pre-populates the Join Builder canvas; it never executes a join.
"""

from __future__ import annotations

import logging
import traceback
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from backend.API_conn.connectors import registry

from backend.recon_engine.entity_join_parser import (
    discover_scopes,
    entity_names,
    parse_entity_join,
)
from backend.recon_engine.llm import reset_llm_outcome

logger = logging.getLogger("recon.entity_join")

router = APIRouter(prefix="/api/recon/entity-join", tags=["recon-entity-join"])


def entities_for(kind: str) -> list[dict[str, Any]]:
    """Live entity list for a connector kind. Raises on an unsupported kind."""
    k = (kind or "").strip().lower()
    if k == "s4":
        from backend.API_conn.connectors.s4_metadata_service import S4MetadataService

        return S4MetadataService().get_entities()
    if k == "ibp":
        from backend.API_conn.connectors.ibp_metadata_service import IBPMetadataService

        return IBPMetadataService().get_entities()
    raise ValueError(f"Unsupported connector kind for entity/join identification: {kind!r}")


def _properties_for(kind: str, names: list[str]) -> dict[str, list[str]]:
    """``{entity: [property names]}`` for one connector.

    Costs no extra network calls: both metadata services parse ``$metadata``
    once and cache it, so every per-entity property lookup is served from that
    same parsed document. An entity whose properties can't be read is skipped.
    """
    k = (kind or "").strip().lower()
    if k == "s4":
        from backend.API_conn.connectors.s4_metadata_service import S4MetadataService

        service = S4MetadataService()
    elif k == "ibp":
        from backend.API_conn.connectors.ibp_metadata_service import IBPMetadataService

        service = IBPMetadataService()
    else:
        return {}

    out: dict[str, list[str]] = {}
    for name in names:
        try:
            props = service.get_entity_properties(name)
        except Exception:  # noqa: BLE001 — one unreadable entity must not break the rest
            continue
        out[name] = [str(p.get("name") or "").strip() for p in props if p.get("name")]
    return out


def live_entity_catalog(kinds: list[str]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Load ``{kind: {"entities": [...], "properties": {entity: [...]}}}``.

    Shared with the mapping-sheet identification route, which needs the same
    live lists to ground and gate its entity/join output. ``properties`` backs
    the field-based entity resolution a side falls back to when the sheet names
    fields but no entity (the IBP case) — it never reaches the LLM prompt, so it
    adds no token cost.

    A connector whose metadata can't be reached is simply absent from the
    catalog (with a warning) rather than failing the request — a missing list
    degrades to "the user names the entities on the canvas", never to a guess.
    """
    catalog: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    for kind in kinds:
        try:
            names = entity_names(entities_for(kind))
        except Exception as exc:  # noqa: BLE001 — degrade, never fail the wizard
            logger.warning("Could not load %s entities for entity/join gating: %s", kind, exc)
            warnings.append(
                f"Could not load the live {kind.upper()} entity list, so any entities the "
                f"sheet names for that side aren't pre-placed: {exc}"
            )
            continue
        if names:
            spec = registry.get_spec(kind)
            catalog[kind] = {
                "entities": names,
                "properties": _properties_for(kind, names),
                # Discovered from the entity names themselves, but only for a
                # connector that actually partitions by planning area. Offered
                # as a choice; never auto-applied.
                "planning_areas": (
                    discover_scopes(names) if spec and spec.has_planning_areas else []
                ),
            }
    return catalog, warnings


class ParseRequest(BaseModel):
    kind: str
    text: str = ""
    # A planning area chosen by hand on Step 1. Outranks whatever the model
    # reads out of the instruction — the human picked it deliberately.
    planning_area: str | None = None


@router.post("/parse")
def parse(req: ParseRequest) -> dict[str, Any]:
    """Parse a plain-language entity/join instruction into a canvas-ready spec."""
    reset_llm_outcome()
    try:
        entities = entities_for(req.kind)
    except Exception as exc:  # noqa: BLE001 — degrade, never 500 the wizard
        return {
            "primary": None,
            "entities": [],
            "join_type": None,
            "keys": None,
            "unresolved": [],
            "planning_area": None,
            "ambiguous": [],
            "warnings": [f"Could not load {req.kind} entities: {exc}"],
            "degraded": True,
            "degraded_reason": str(exc),
            "provider": None,
            "detail": traceback.format_exc(),
        }
    return parse_entity_join(
        req.text,
        entities,
        (req.kind or "").strip().lower(),
        (req.planning_area or "").strip() or None,
    )


@router.get("/planning-areas")
def planning_areas(kind: str) -> dict[str, Any]:
    """The planning areas discovered on a connector, for manual selection.

    IBP qualifies its entity sets by planning area, so the same planning level
    appears once per area. When neither the mapping sheet nor the typed
    instruction names an area, the user picks one from this list — the wizard
    never chooses for them, because the wrong area returns entirely wrong data.
    Degrades to an empty list rather than failing the step.

    Connectors that don't partition by planning area (S/4) return an empty list
    from the registry capability, so no spurious choice is offered there.
    """
    spec = registry.get_spec(kind)
    if spec is None or not spec.has_planning_areas:
        return {"planning_areas": [], "degraded": False, "degraded_reason": None}
    try:
        names = entity_names(entities_for(kind))
    except Exception as exc:  # noqa: BLE001 — degrade, never 500 the wizard
        logger.warning("Could not load %s entities for planning areas: %s", kind, exc)
        return {"planning_areas": [], "degraded": True, "degraded_reason": str(exc)}
    return {"planning_areas": discover_scopes(names), "degraded": False, "degraded_reason": None}
