from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

import pandas as pd
import requests

from backend.API_conn.config.config_loader import load_config, resolve_verify
from backend.API_conn.connectors.base_connector import SAPConnector
from backend.API_conn.odata_utils import sap_odata_date_to_ddmmyyyy, to_odata_datetime_literal


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
        self.verify_ssl = resolve_verify(cfg)

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

    def _query_page(self, entity_set: str, params: dict[str, Any]) -> pd.DataFrame:
        """Single OData page read for ``entity_set``."""
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

    def _query(
        self,
        entity_set: str,
        params: dict[str, Any],
        *,
        paginate: bool = False,
        page_size: int = 5000,
    ) -> pd.DataFrame:
        """Central chokepoint for entity reads.

        ``paginate=False`` (default) is a single page read — used for bounded
        calls (``$top``-capped previews). ``paginate=True`` loops ``$skip`` in
        ``page_size`` steps until a page comes back shorter than
        ``page_size`` — used for real extraction (batch/full pulls).
        """
        if not paginate:
            return self._query_page(entity_set, params)

        pages: list[pd.DataFrame] = []
        skip = 0
        while True:
            page = self._query_page(
                entity_set, {**params, "$top": str(page_size), "$skip": str(skip)}
            )
            if page.empty:
                break
            pages.append(page)
            if len(page) < page_size:
                break
            skip += page_size
        if not pages:
            return pd.DataFrame()
        return pd.concat(pages, ignore_index=True)

    @staticmethod
    def date_range_filter(field: str, start, end) -> str:
        """``$filter`` clause for an inclusive ``[start, end]`` date-range
        window on ``field`` (OData V2 ``datetime'...'`` literals)."""
        return (
            f"{field} ge {to_odata_datetime_literal(start)} and "
            f"{field} le {to_odata_datetime_literal(end)}"
        )

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
        selection is mandatory. There is NO default/fallback selection — the
        caller must pass an explicit list; an empty selection raises below.
        """
        selectable = {
            p["name"]
            for p in self.get_entity_properties(entity_name)
            if p["selectable"]
        }

        requested = selected_properties or []
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

    def preview_column(
        self,
        entity_name: str,
        field: str,
        date_filter: tuple[Any, Any] | None = None,
    ) -> pd.Series:
        """Cheap, paginated single-column pull — used by the date-union batch
        planner to get every distinct date (and per-date row count) without
        pulling full rows. ``date_filter`` is an optional ``(start, end)``
        window, same semantics as :meth:`fetch_entity`."""
        selected = self._resolve_selection(entity_name, [field])
        params: dict[str, Any] = {"$select": ",".join(selected)}
        if date_filter is not None:
            params["$filter"] = self.date_range_filter(field, *date_filter)
        df = self._query(entity_name, params, paginate=True)
        if df.empty or field not in df.columns:
            return pd.Series([], dtype=object)
        return df[field]

    def count_entity(self, entity_name: str) -> int | None:
        """Cheap total row count via OData V2 ``$inlinecount=allpages`` with
        ``$top=0`` — one half of the suspend/resume staleness fingerprint
        (see ``auto_pipeline.data_fingerprint``). IBP rejects a
        selection-less read, so ``$select`` is pinned to one selectable
        property purely to satisfy that requirement; the value itself is
        never used. Returns ``None`` if there is no selectable property at
        all, or the response carries no ``__count``, so a caller can degrade
        gracefully rather than assume staleness from a missing signal.
        """
        selectable = [p["name"] for p in self.get_entity_properties(entity_name) if p["selectable"]]
        if not selectable:
            return None
        params = {
            "$format": "json", "$select": selectable[0],
            "$inlinecount": "allpages", "$top": "0",
        }
        response = self.session.get(
            f"{self._service_base_url()}/{entity_name}",
            params=params,
            auth=self._auth(),
            headers=self._headers(),
            verify=self.verify_ssl,
            timeout=60,
        )
        if not response.ok:
            raise RuntimeError(_sap_error_message(response))
        count = response.json().get("d", {}).get("__count")
        return int(count) if count is not None else None

    def fetch_entity(
        self,
        entity_name: str,
        selected_properties: list[str],
        date_filter: tuple[str, Any, Any] | None = None,
    ) -> pd.DataFrame:
        """``date_filter``, if given, is ``(field, start, end)`` — windows the
        pull to an inclusive date range instead of the full dataset."""
        selected = self._resolve_selection(entity_name, selected_properties)
        params: dict[str, Any] = {"$select": ",".join(selected)}
        if date_filter is not None:
            field, start, end = date_filter
            params["$filter"] = self.date_range_filter(field, start, end)
        df = self._query(entity_name, params, paginate=True)
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
