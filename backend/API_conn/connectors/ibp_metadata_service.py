from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

import pandas as pd
import requests

from backend.API_conn.config.config_loader import load_config
from backend.API_conn.connectors.base_connector import SAPConnector
from backend.API_conn.odata_utils import sap_odata_date_to_ddmmyyyy


@dataclass
class IBPServiceConfig:
    base_url: str
    service: str
    username: str
    password: str
    client: str | None = None


# Process-level metadata cache keyed by the service base URL. The app has no
# per-session layer today, so a module-level cache is the practical equivalent
# of "cached per session" — parsing the (large) $metadata document once per
# service is what we want to avoid repeating on every entity/property lookup.
_METADATA_CACHE: dict[str, "_ParsedMetadata"] = {}


@dataclass
class _ParsedMetadata:
    # set_name -> local EntityType name
    entity_sets: dict[str, str]
    # local EntityType name -> [ {"name", "type", "role", "label",
    #                             "value_list", "filter_restriction"}, ... ]
    entity_types: dict[str, list[dict[str, Any]]]


def _local(tag: str) -> str:
    """Return the local name of an XML tag, stripping any ``{namespace}``.

    EDMX documents are namespaced (edmx / edm), and the exact namespace URI
    varies by OData/EDM version. Matching on the local name keeps parsing
    robust across services.
    """
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _type_local_name(qualified: str) -> str:
    """`Namespace.TypeName` (or `Collection(Namespace.TypeName)`) -> `TypeName`."""
    value = qualified.strip()
    if value.startswith("Collection(") and value.endswith(")"):
        value = value[len("Collection("):-1]
    return value.rsplit(".", 1)[-1]


def _is_selectable(prop: dict[str, Any]) -> bool:
    """Whether a property can appear in ``$select`` for an IBP planning service.

    IBP's PLANNING_DATA_API_SRV exposes properties in ``$metadata`` that it
    then rejects in ``$select`` (e.g. ``*_REL`` relative-period keys, internal
    ID/VERSION/SCENARIO/MASTER_DATA_TYPE fields — it returns HTTP 400 "This
    service cannot be used to extract master data" / "You cannot add property
    X to $select"). Empirically, the selectable set is:
      - every ``measure`` (key figure), and
      - every ``dimension`` that carries a ``filter-restriction`` annotation
        (real attributes and time characteristics have one; the internal
        fields do not).
    Properties with no/other aggregation-role are assumed selectable and left
    to the server to validate.
    """
    role = prop.get("role")
    if role == "measure":
        return True
    if role == "dimension":
        return bool(prop.get("filter_restriction"))
    return True


class IBPMetadataService(SAPConnector):
    """Generic, metadata-driven access to a SAP IBP OData V2 service.

    Discovers EntitySets and their properties from ``$metadata`` and fetches
    preview / full datasets dynamically — no hardcoded entity or column names.
    Written generically so S/4 (or any OData V2 service) can reuse it later.
    """

    def __init__(self, config_key: str = "ibp"):
        config_all = load_config()

        if config_key not in config_all:
            raise RuntimeError(f"Missing '{config_key}' config")

        cfg = config_all[config_key]

        super().__init__(cfg)

        self.cfg = IBPServiceConfig(
            base_url=str(cfg["base_url"]),
            service=str(cfg["service"]),
            username=str(cfg["username"]),
            password=str(cfg["password"]),
            client=str(cfg.get("client")) if cfg.get("client") else None,
        )

        self.session = requests.Session()
        self.verify_ssl = False

    # ------------------------------------------------------------------
    # HTTP plumbing (mirrors IBPDemandConnector)
    # ------------------------------------------------------------------

    def _service_base_url(self) -> str:
        return f"{self.cfg.base_url}/sap/opu/odata/{self.cfg.service}"

    def _auth(self):
        return (self.cfg.username, self.cfg.password)

    def _headers(self, accept: str = "application/json") -> dict[str, str]:
        headers = {"Accept": accept}
        if self.cfg.client:
            headers["sap-client"] = self.cfg.client
        return headers

    def _query(self, entity_set: str, params: dict[str, Any]) -> pd.DataFrame:
        """Run a single OData read for ``entity_set`` with the given query params.

        Central chokepoint for reads so future work (pagination via
        ``$skip``/``$skiptoken``, chunked loading) can extend it without
        touching the public ``preview_entity`` / ``fetch_entity`` signatures.
        """
        url = f"{self._service_base_url()}/{entity_set}"

        # OData V2 uses `$` params; keep $format=json always present.
        query_params = {"$format": "json", **params}

        response = self.session.get(
            url,
            params=query_params,
            auth=self._auth(),
            headers=self._headers(),
            verify=self.verify_ssl,
            timeout=120,
        )

        if not response.ok:
            raise RuntimeError(_sap_error_message(response))

        payload = response.json()
        rows = payload.get("d", {}).get("results", [])

        df = pd.DataFrame(rows)

        # OData V2 embeds a `__metadata` object per row — drop it.
        if "__metadata" in df.columns:
            df = df.drop(columns=["__metadata"])

        return _normalize_odata_dates(df)

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    def _fetch_metadata_xml(self) -> str:
        url = f"{self._service_base_url()}/$metadata"

        response = self.session.get(
            url,
            auth=self._auth(),
            headers=self._headers(accept="application/xml"),
            verify=self.verify_ssl,
            timeout=120,
        )
        response.raise_for_status()
        return response.text

    def _parse_metadata(self, force_refresh: bool = False) -> _ParsedMetadata:
        cache_key = self._service_base_url()

        if not force_refresh and cache_key in _METADATA_CACHE:
            return _METADATA_CACHE[cache_key]

        xml_text = self._fetch_metadata_xml()
        root = ET.fromstring(xml_text)

        entity_sets: dict[str, str] = {}
        entity_types: dict[str, list[dict[str, str]]] = {}

        for elem in root.iter():
            tag = _local(elem.tag)

            if tag == "EntitySet":
                name = elem.get("Name")
                entity_type = elem.get("EntityType")
                if name and entity_type:
                    entity_sets[name] = _type_local_name(entity_type)

            elif tag == "EntityType":
                type_name = elem.get("Name")
                if not type_name:
                    continue
                props: list[dict[str, Any]] = []
                for child in elem:
                    if _local(child.tag) != "Property":
                        continue
                    prop_name = child.get("Name")
                    if not prop_name:
                        continue
                    # SAP annotations are namespaced (sap:...); index the
                    # attribute bag by local name so we can read them portably.
                    attrs = {_local(k): v for k, v in child.attrib.items()}
                    props.append(
                        {
                            "name": prop_name,
                            "type": attrs.get("Type", ""),
                            "role": attrs.get("aggregation-role"),
                            "label": attrs.get("label") or attrs.get("heading"),
                            "value_list": "value-list" in attrs,
                            "filter_restriction": attrs.get("filter-restriction"),
                        }
                    )
                entity_types[type_name] = props

        parsed = _ParsedMetadata(
            entity_sets=entity_sets,
            entity_types=entity_types,
        )
        _METADATA_CACHE[cache_key] = parsed
        return parsed

    def get_entities(self) -> list[dict[str, str]]:
        parsed = self._parse_metadata()
        return [
            {"name": set_name, "entity_type": type_name}
            for set_name, type_name in sorted(parsed.entity_sets.items())
        ]

    def get_entity_properties(self, entity_name: str) -> list[dict[str, Any]]:
        """Return properties for an entity, each flagged with ``selectable``.

        Shape: ``{name, type, role, label, selectable}``. ``role`` is the SAP
        aggregation-role (``dimension`` / ``measure`` / ``None``); ``selectable``
        tells the UI which properties can actually go into ``$select`` (see
        ``_is_selectable``).
        """
        parsed = self._parse_metadata()

        if entity_name not in parsed.entity_sets:
            raise ValueError(f"Unknown entity set: {entity_name!r}")

        type_name = parsed.entity_sets[entity_name]
        props = parsed.entity_types.get(type_name)

        if props is None:
            raise ValueError(
                f"EntityType {type_name!r} for entity {entity_name!r} "
                f"not found in metadata"
            )

        return [
            {
                "name": p["name"],
                "type": p["type"],
                "role": p.get("role"),
                "label": p.get("label"),
                "selectable": _is_selectable(p),
            }
            for p in props
        ]

    def default_properties(self, entity_name: str, limit: int = 10) -> list[str]:
        """A small, *mutually-compatible* starter selection for previewing.

        Picks master-data attributes (dimensions carrying a value-list) and
        key figures (measures) only — deliberately excluding time
        characteristics, since IBP rejects selecting several period levels at
        once ("You cannot select period IDs which have different period level
        numbers"). Every property here is individually selectable, so the
        initial preview loads without the user having to guess a valid combo.
        """
        parsed = self._parse_metadata()
        type_name = parsed.entity_sets.get(entity_name)
        raw = parsed.entity_types.get(type_name, []) if type_name else []

        attrs = [p["name"] for p in raw if p.get("role") == "dimension" and p.get("value_list")]
        measures = [p["name"] for p in raw if p.get("role") == "measure"]

        chosen = attrs[:6] + measures[: max(0, limit - min(6, len(attrs)))]
        if not chosen:
            # Fallback: any selectable property.
            chosen = [p["name"] for p in raw if _is_selectable(p)][:limit]
        return chosen[:limit]

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def _resolve_selection(
        self,
        entity_name: str,
        selected_properties: list[str] | None,
    ) -> list[str]:
        """Validate a requested selection against the entity's selectable props.

        IBP requires at least one attribute/key figure in ``$select``, so a
        selection is mandatory; falls back to ``default_properties`` when the
        caller passes nothing.
        """
        selectable = {
            p["name"]
            for p in self.get_entity_properties(entity_name)
            if p["selectable"]
        }

        requested = selected_properties or self.default_properties(entity_name)
        selected = [p for p in requested if p in selectable]

        if not selected:
            raise ValueError(
                "No selectable properties for entity "
                f"{entity_name!r} (requested: {selected_properties}). "
                "IBP requires at least one attribute or key figure."
            )
        return selected

    def preview_entity(
        self,
        entity_name: str,
        selected_properties: list[str] | None = None,
        top: int = 10,
    ) -> pd.DataFrame:
        # IBP planning services reject a bare read ("You must pass at least one
        # attribute or one key figure"), so preview is always $select-driven.
        selected = self._resolve_selection(entity_name, selected_properties)
        df = self._query(entity_name, {"$select": ",".join(selected), "$top": str(top)})
        return _ensure_columns(df, selected)

    def fetch_entity(
        self,
        entity_name: str,
        selected_properties: list[str],
    ) -> pd.DataFrame:
        selected = self._resolve_selection(entity_name, selected_properties)
        # No $top — pull the full dataset. Comma-joined with no spaces.
        df = self._query(entity_name, {"$select": ",".join(selected)})
        return _ensure_columns(df, selected)


def _ensure_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Guarantee column presence/order — a selected field may be absent from
    the rows if it came back all-null from the server."""
    for col in columns:
        if col not in df.columns:
            df[col] = None
    return df[columns]


def _sap_error_message(response: requests.Response) -> str:
    """Extract the human-readable SAP OData error, falling back to raw text.

    IBP returns ``{"error": {"message": {"value": "..."}}}`` — surfacing that
    value (e.g. "You cannot select period IDs which have different period
    level numbers") is far more actionable than a bare HTTP 400.
    """
    try:
        body = response.json()
        msg = body.get("error", {}).get("message", {})
        value = msg.get("value") if isinstance(msg, dict) else msg
        if value:
            return f"SAP IBP error (HTTP {response.status_code}): {value}"
    except Exception:
        pass
    return f"SAP IBP error (HTTP {response.status_code}): {response.text[:300]}"


def _normalize_odata_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Convert any OData V2 ``/Date(...)/`` cell to ``dd.mm.yyyy``.

    Applied generically (not to one hardcoded column) so downstream
    date-alignment works regardless of which date property the user selects.
    ``sap_odata_date_to_ddmmyyyy`` passes non-date values through unchanged.
    """
    if df.empty:
        return df

    for col in df.columns:
        series = df[col].astype("object")
        if series.map(lambda v: isinstance(v, str) and v.startswith("/Date(")).any():
            df[col] = series.map(sap_odata_date_to_ddmmyyyy)

    return df
