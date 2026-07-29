"""Connector registry — the single allow-list of live-fetch connectors.

There is deliberately no dynamic plugin discovery here: the reconciliation
tool ships two real, hand-written connectors (S/4HANA source, IBP target), and
Excel upload is a *file* path, not a live connector. This module answers two
questions the sheet-driven identification flow needs:

* Which connector *kinds* actually exist in code (the registered set)?
* Which of those are *configured & enabled* right now (the credentials in
  ``sap_config.yaml`` — NOT ``.env`` — with ``enabled: true``)?

The LLM that infers "which system does this sheet describe" is constrained to
the CONFIGURED set returned here. Anything it names outside this list is
flagged, never coerced to the nearest match — a wrong system silently fetches
entirely wrong data, so the discipline mirrors the operations allow-list.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.API_conn.config.config_loader import load_config

# Roles a connector may occupy in a reconciliation. Kept as bare strings to
# match the existing free-text source_type/target_type convention.
SOURCE = "source"
TARGET = "target"

# Fields every SAP connector block must carry to count as "configured".
_REQUIRED_FIELDS = ("base_url", "service", "username", "password")


@dataclass(frozen=True)
class ConnectorSpec:
    """Static metadata for a connector that exists in code."""

    kind: str              # canonical id used by source_type/target_type ("s4"/"ibp")
    config_key: str        # top-level key in sap_config.yaml
    role: str              # SOURCE or TARGET
    label: str             # human-facing name
    ui_connector_id: str   # the frontend CONNECTOR_OPTIONS id
    table_prefix_hint: str # naming-convention hint surfaced to the LLM
    # Whether this connector partitions its entity sets by SAP IBP planning
    # area. Where true, the same planning level is exposed once per area under
    # identical field names, so the area must be established before an entity
    # can be identified. Declared here rather than guessed from entity names, so
    # a connector without planning areas is never offered a choice it doesn't have.
    has_planning_areas: bool = False


# The registered connectors. This is the ONLY place new live connectors get
# added — keep it in lockstep with the actual connector classes and the
# frontend CONNECTOR_OPTIONS ids.
CONNECTOR_SPECS: tuple[ConnectorSpec, ...] = (
    ConnectorSpec(
        kind="s4",
        config_key="s4",
        role=SOURCE,
        label="SAP S/4HANA",
        ui_connector_id="sap_s4hana",
        table_prefix_hint=
            "SAP S/4HANA mapping sheets typically contain technical references "
            "such as VBAP-MATNR, VBAP-WERKS, VBEP-EDATU along with business "
            "descriptions like Material, Production Plant, Requested Quantity, "
            "and Requested Delivery Date. When identifying candidate source "
            "fields, prefer the business descriptions over the technical "
            "TABLE-FIELD identifiers.",
    ),
    ConnectorSpec(
        kind="ibp",
        config_key="ibp",
        role=TARGET,
        label="SAP IBP",
        ui_connector_id="sap_ibp",
        table_prefix_hint=
            "SAP IBP mapping sheets typically contain technical planning object, "
            "attribute, and key figure names such as PRDID, LOCID, "
            "SALESORDERREQUEST, and PERIODID0_TSTAMP. When identifying candidate "
            "target fields, prefer these technical field names over business labels "
            "such as Product ID or Location ID.",
        has_planning_areas=True,
    ),
)

_BY_KIND = {spec.kind: spec for spec in CONNECTOR_SPECS}


def get_spec(kind: str | None) -> ConnectorSpec | None:
    """Return the spec for a kind, or None if the kind is not registered."""
    if not kind:
        return None
    return _BY_KIND.get(str(kind).strip().lower())


def is_registered_kind(kind: str | None) -> bool:
    """True when ``kind`` names a connector that actually exists in code."""
    return get_spec(kind) is not None


def _block_is_configured(block: Any) -> bool:
    """A connector is configured when its block exists, ``enabled`` is truthy,
    and every credential field is present and non-empty.

    We honor ``enabled`` deliberately: the flag was previously written into the
    YAML but never read, so an operator who sets ``enabled: false`` reasonably
    expects the connector to disappear from the selectable set.
    """
    if not isinstance(block, dict):
        return False
    if not block.get("enabled", False):
        return False
    return all(str(block.get(field, "") or "").strip() for field in _REQUIRED_FIELDS)


def _load_config_safe() -> dict[str, Any]:
    try:
        config = load_config()
    except Exception:
        return {}
    return config if isinstance(config, dict) else {}


def get_connectors(config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return every registered connector with its live configured/enabled state.

    ``config`` is injectable for tests; by default it reads sap_config.yaml.
    """
    cfg = config if config is not None else _load_config_safe()
    out: list[dict[str, Any]] = []
    for spec in CONNECTOR_SPECS:
        block = cfg.get(spec.config_key)
        out.append(
            {
                "kind": spec.kind,
                "role": spec.role,
                "label": spec.label,
                "connector_id": spec.ui_connector_id,
                "table_prefix_hint": spec.table_prefix_hint,
                "configured": _block_is_configured(block),
            }
        )
    return out


def get_configured_connectors(
    config: dict[str, Any] | None = None, role: str | None = None
) -> list[dict[str, Any]]:
    """The allow-list: connectors that are configured & enabled right now.

    Optionally narrowed to a single ``role`` (SOURCE/TARGET) — the source-side
    identification only ever picks among source connectors, and vice versa.
    """
    connectors = [c for c in get_connectors(config) if c["configured"]]
    if role is not None:
        connectors = [c for c in connectors if c["role"] == role]
    return connectors


def configured_kinds(config: dict[str, Any] | None = None) -> set[str]:
    """The set of connector kinds that are configured & enabled."""
    return {c["kind"] for c in get_configured_connectors(config)}
