from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
import requests

from backend.API_conn.config.config_loader import load_config, resolve_verify
from backend.API_conn.connectors.base_connector import SAPConnector
from backend.API_conn.odata_utils import sap_odata_date_to_ddmmyyyy


@dataclass
class S4ServiceConfig:
    base_url: str
    service: str
    username: str
    password: str
    client: str | None = None


# Process-level metadata cache keyed by the service base URL (see the IBP
# service for the rationale — parse the large $metadata document once).
_METADATA_CACHE: dict[str, "_ParsedMetadata"] = {}

# How many rows to sample per entity when building a *joined* preview. Fetching
# only 10 rows per side often yields no matched join rows, so we sample more,
# merge, and show the first 10 matched. The final import is uncapped.
PREVIEW_SAMPLE_TOP = 200


@dataclass
class _EntityType:
    keys: list[str] = field(default_factory=list)
    properties: list[dict[str, str]] = field(default_factory=list)  # [{name,type}]
    # nav name -> {"relationship": assoc_local_name, "to_role": str}
    navigations: dict[str, dict[str, str]] = field(default_factory=dict)


@dataclass
class _ParsedMetadata:
    entity_sets: dict[str, str]                 # set_name -> local EntityType name
    entity_types: dict[str, _EntityType]        # local EntityType name -> _EntityType
    associations: dict[str, dict[str, tuple[str, str]]]  # assoc -> {role: (type_local, multiplicity)}


def _local(tag: str) -> str:
    """Local name of an XML tag/attr, stripping any ``{namespace}`` prefix."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _type_local_name(qualified: str | None) -> str:
    """`Namespace.TypeName` or `Collection(Namespace.TypeName)` -> `TypeName`."""
    if not qualified:
        return ""
    value = qualified.strip()
    if value.startswith("Collection(") and value.endswith(")"):
        value = value[len("Collection("):-1]
    return value.rsplit(".", 1)[-1]


def _cardinality_label(from_mult: str | None, to_mult: str | None) -> str:
    """Human label like ``1:N`` / ``1:1`` from OData ``End`` multiplicities."""
    def side(m: str | None) -> str:
        return "N" if m == "*" else "1"
    return f"{side(from_mult)}:{side(to_mult)}"


class S4MetadataService(SAPConnector):
    """Generic, metadata-driven access to a SAP S/4HANA OData V2 service.

    Discovers EntitySets, properties, and relationships (Associations /
    NavigationProperties) from ``$metadata``, and builds joined datasets across
    multiple entities via pandas merges — no hardcoded entities, columns, or
    joins. Mirrors ``IBPMetadataService``; the S/4 service path carries the
    extra ``/sap/`` segment.
    """

    def __init__(self, config_key: str = "s4"):
        config_all = load_config()

        if config_key not in config_all:
            raise RuntimeError(f"Missing '{config_key}' config")

        cfg = config_all[config_key]
        super().__init__(cfg)

        self.cfg = S4ServiceConfig(
            base_url=str(cfg["base_url"]),
            service=str(cfg["service"]),
            username=str(cfg["username"]),
            password=str(cfg["password"]),
            client=str(cfg.get("client")) if cfg.get("client") else None,
        )

        self.session = requests.Session()
        self.verify_ssl = resolve_verify(cfg)

    # ------------------------------------------------------------------
    # HTTP plumbing (mirrors S4SalesOrderConnector)
    # ------------------------------------------------------------------

    def _service_base_url(self) -> str:
        return f"{self.cfg.base_url}/sap/opu/odata/sap/{self.cfg.service}"

    def _auth(self):
        return (self.cfg.username, self.cfg.password)

    def _headers(self, accept: str = "application/json") -> dict[str, str]:
        headers = {"Accept": accept}
        if self.cfg.client:
            headers["SAP-Client"] = self.cfg.client
        return headers

    def _query(self, entity_set: str, params: dict[str, Any]) -> pd.DataFrame:
        """Single OData read for ``entity_set``. Central chokepoint so future
        pagination (``$skip``/``$skiptoken``) can be added without changing the
        public methods."""
        url = f"{self._service_base_url()}/{entity_set}"
        query_params = {"$format": "json", **params}

        response = self.session.get(
            url,
            params=query_params,
            auth=self._auth(),
            headers=self._headers(),
            verify=self.verify_ssl,
            timeout=180,
        )
        if not response.ok:
            raise RuntimeError(_sap_error_message(response))

        payload = response.json()
        rows = payload.get("d", {}).get("results", [])

        df = pd.DataFrame(rows)
        # OData V2 embeds a `__metadata` object (and deferred nav objects) per
        # row — keep only the plain columns.
        drop = [c for c in df.columns if c == "__metadata"]
        if drop:
            df = df.drop(columns=drop)
        return _normalize_odata_dates(df)

    # ------------------------------------------------------------------
    # Metadata parsing
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

        root = ET.fromstring(self._fetch_metadata_xml())

        entity_sets: dict[str, str] = {}
        entity_types: dict[str, _EntityType] = {}
        associations: dict[str, dict[str, tuple[str, str]]] = {}

        for elem in root.iter():
            tag = _local(elem.tag)

            if tag == "EntitySet":
                name = elem.get("Name")
                etype = elem.get("EntityType")
                if name and etype:
                    entity_sets[name] = _type_local_name(etype)

            elif tag == "EntityType":
                type_name = elem.get("Name")
                if not type_name:
                    continue
                et = _EntityType()
                for child in elem:
                    ctag = _local(child.tag)
                    if ctag == "Key":
                        for pref in child:
                            if _local(pref.tag) == "PropertyRef" and pref.get("Name"):
                                et.keys.append(pref.get("Name"))
                    elif ctag == "Property":
                        pname = child.get("Name")
                        if pname:
                            et.properties.append(
                                {"name": pname, "type": child.get("Type", "")}
                            )
                    elif ctag == "NavigationProperty":
                        nav = child.get("Name")
                        if nav:
                            et.navigations[nav] = {
                                "relationship": _type_local_name(child.get("Relationship")),
                                "to_role": child.get("ToRole", ""),
                            }
                entity_types[type_name] = et

            elif tag == "Association":
                name = elem.get("Name")
                if not name:
                    continue
                ends: dict[str, tuple[str, str]] = {}
                for child in elem:
                    if _local(child.tag) == "End":
                        role = child.get("Role")
                        if role:
                            ends[role] = (
                                _type_local_name(child.get("Type")),
                                child.get("Multiplicity", ""),
                            )
                associations[name] = ends

        parsed = _ParsedMetadata(entity_sets, entity_types, associations)
        _METADATA_CACHE[cache_key] = parsed
        return parsed

    # ------------------------------------------------------------------
    # Public metadata API
    # ------------------------------------------------------------------

    def get_entities(self) -> list[dict[str, str]]:
        parsed = self._parse_metadata()
        return [
            {"name": s, "entity_type": t}
            for s, t in sorted(parsed.entity_sets.items())
        ]

    def _entity_type(self, entity_name: str) -> _EntityType:
        parsed = self._parse_metadata()
        if entity_name not in parsed.entity_sets:
            raise ValueError(f"Unknown entity set: {entity_name!r}")
        type_name = parsed.entity_sets[entity_name]
        et = parsed.entity_types.get(type_name)
        if et is None:
            raise ValueError(
                f"EntityType {type_name!r} for entity {entity_name!r} not found"
            )
        return et

    def get_entity_properties(self, entity_name: str) -> list[dict[str, Any]]:
        et = self._entity_type(entity_name)
        keyset = set(et.keys)
        return [
            {"name": p["name"], "type": p["type"], "is_key": p["name"] in keyset}
            for p in et.properties
        ]

    def get_entity_keys(self, entity_name: str) -> list[str]:
        return list(self._entity_type(entity_name).keys)

    def get_entity_relationships(self, entity_name: str) -> list[dict[str, Any]]:
        """Resolve each NavigationProperty to a target EntitySet, cardinality,
        and suggested join keys.

        Join keys are suggested from the *shared key names* between the primary
        and target entity types (this service exposes no ReferentialConstraints).
        Falls back to shared non-key property names. Always overridable by the
        caller.
        """
        parsed = self._parse_metadata()
        et = self._entity_type(entity_name)
        primary_type = parsed.entity_sets[entity_name]
        type_to_set = _invert_entity_sets(parsed.entity_sets)

        rels: list[dict[str, Any]] = []
        for nav, info in et.navigations.items():
            ends = parsed.associations.get(info["relationship"], {})
            target_type, to_mult = ends.get(info["to_role"], ("", ""))
            if not target_type:
                continue
            target_set = type_to_set.get(target_type)
            if not target_set:
                continue

            # cardinality: this entity's End multiplicity vs the target's.
            from_mult = next(
                (m for r, (t, m) in ends.items() if r != info["to_role"]),
                "",
            )
            rels.append(
                {
                    "nav": nav,
                    "target_entity": target_set,
                    "target_type": target_type,
                    "cardinality": _cardinality_label(from_mult, to_mult),
                    "suggested_keys": self._suggest_keys(primary_type, target_type),
                }
            )
        rels.sort(key=lambda r: r["target_entity"])
        return rels

    def _suggest_keys(self, primary_type: str, target_type: str) -> list[str]:
        parsed = self._parse_metadata()
        p = parsed.entity_types.get(primary_type)
        t = parsed.entity_types.get(target_type)
        if not p or not t:
            return []
        p_keys, t_keys = set(p.keys), set(t.keys)
        shared_keys = [k for k in p.keys if k in t_keys]  # preserve primary order
        if shared_keys:
            return shared_keys
        # Fallback: shared property names (excluding keys already handled).
        t_props = {pr["name"] for pr in t.properties}
        return [pr["name"] for pr in p.properties if pr["name"] in t_props][:3]

    # ------------------------------------------------------------------
    # Data — single entity + joined
    # ------------------------------------------------------------------

    def _resolve_props(self, entity_name: str, requested: list[str] | None) -> list[str]:
        valid = {p["name"] for p in self.get_entity_properties(entity_name)}
        if requested:
            chosen = [p for p in requested if p in valid]
        else:
            # sensible default: keys + first few properties
            keys = self.get_entity_keys(entity_name)
            extras = [p["name"] for p in self.get_entity_properties(entity_name)
                      if p["name"] not in keys]
            chosen = keys + extras[:5]
        if not chosen:
            raise ValueError(f"No valid properties selected for {entity_name!r}")
        return chosen

    def preview_entity(
        self,
        entity_name: str,
        selected_properties: list[str] | None = None,
        top: int = 10,
    ) -> pd.DataFrame:
        selected = self._resolve_props(entity_name, selected_properties)
        df = self._query(entity_name, {"$select": ",".join(selected), "$top": str(top)})
        return _ensure_columns(df, selected)

    def preview_join(self, spec: dict[str, Any]) -> pd.DataFrame:
        return self._build_joined(spec, sample_top=PREVIEW_SAMPLE_TOP).head(10)

    def fetch_joined_dataset(self, spec: dict[str, Any]) -> pd.DataFrame:
        return self._build_joined(spec, sample_top=None)

    def _build_joined(self, spec: dict[str, Any], sample_top: int | None) -> pd.DataFrame:
        """Fetch the primary entity + each joined entity and merge them.

        ``spec`` shape::

            {
              "primary": {"entity": str, "properties": [str, ...]},
              "joins": [
                {"entity": str, "properties": [str],
                 "type": "left"|"inner",
                 "keys": [{"left": str, "right": str}, ...]},
                ...
              ]
            }

        Each entity is queried with ``$select = properties ∪ its join keys`` so
        the merge always has the keys available even when the user didn't select
        them. Joins are applied against the primary (star). Non-key column-name
        collisions are suffixed with the joined entity's short name; duplicate
        key columns are dropped.
        """
        primary = spec.get("primary") or {}
        primary_entity = primary.get("entity")
        if not primary_entity:
            raise ValueError("spec.primary.entity is required")

        joins = spec.get("joins") or []

        # ---- primary ----
        primary_props = self._resolve_props(primary_entity, primary.get("properties"))
        left_keys_needed = _unique(
            k["left"] for j in joins for k in (j.get("keys") or []) if k.get("left")
        )
        primary_select = _unique(primary_props + left_keys_needed)
        params = {"$select": ",".join(primary_select)}
        if sample_top:
            params["$top"] = str(sample_top)
        result = _ensure_columns(self._query(primary_entity, params), primary_select)

        # Output columns accumulate the user's selections in a stable order.
        out_cols: list[str] = list(primary_props)

        # ---- each join ----
        for j in joins:
            j_entity = j.get("entity")
            if not j_entity:
                continue
            how = (j.get("type") or "left").lower()
            if how not in ("left", "inner"):
                how = "left"
            key_pairs = [
                (k["left"], k["right"])
                for k in (j.get("keys") or [])
                if k.get("left") and k.get("right")
            ]
            if not key_pairs:
                raise ValueError(f"Join on {j_entity!r} has no key pairs")

            j_props = self._resolve_props(j_entity, j.get("properties"))
            right_keys = _unique(r for _, r in key_pairs)
            j_select = _unique(j_props + right_keys)
            params = {"$select": ",".join(j_select)}
            if sample_top:
                params["$top"] = str(sample_top)
            right_df = _ensure_columns(self._query(j_entity, params), j_select)

            left_on = [l for l, _ in key_pairs]
            right_on = [r for _, r in key_pairs]

            short = _short_name(j_entity)
            # Rename non-key joined columns that collide with existing output.
            rename: dict[str, str] = {}
            for col in j_props:
                if col in right_on:
                    continue
                if col in result.columns or col in out_cols:
                    rename[col] = f"{col}_{short}"
            right_df = right_df.rename(columns=rename)

            result = result.merge(
                right_df,
                left_on=left_on,
                right_on=right_on,
                how=how,
                suffixes=("", f"_{short}"),
            )
            # Drop duplicate right-key columns when they differ in name from left.
            for l, r in key_pairs:
                if r != l and r in result.columns:
                    result = result.drop(columns=[r], errors="ignore")

            for col in j_props:
                if col in right_on:
                    continue
                out_cols.append(rename.get(col, col))

        out_cols = _unique(c for c in out_cols if c in result.columns)
        return result[out_cols] if out_cols else result


# ----------------------------------------------------------------------
# Module helpers
# ----------------------------------------------------------------------

def _invert_entity_sets(entity_sets: dict[str, str]) -> dict[str, str]:
    """type_local_name -> entity_set_name (first match wins)."""
    out: dict[str, str] = {}
    for s, t in entity_sets.items():
        out.setdefault(t, s)
    return out


def _short_name(entity: str) -> str:
    """A compact suffix for disambiguating collided columns (e.g. drop the
    leading ``A_``)."""
    return entity[2:] if entity.startswith("A_") else entity


def _unique(items) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


def _ensure_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    for col in columns:
        if col not in df.columns:
            df[col] = None
    return df[columns]


def _sap_error_message(response: requests.Response) -> str:
    """Human-readable SAP OData error, falling back to raw text."""
    try:
        body = response.json()
        msg = body.get("error", {}).get("message", {})
        value = msg.get("value") if isinstance(msg, dict) else msg
        if value:
            return f"SAP S/4HANA error (HTTP {response.status_code}): {value}"
    except Exception:
        pass
    return f"SAP S/4HANA error (HTTP {response.status_code}): {response.text[:300]}"


def _normalize_odata_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Convert any OData V2 ``/Date(...)/`` cell to ``dd.mm.yyyy`` generically.

    Only string cells are transformed — non-strings (notably pandas ``NaN``
    from unmatched left-join rows) are left untouched so they stay null and are
    rendered as empty by the route's ``fillna("")`` rather than the literal
    string ``"nan"``.
    """
    if df.empty:
        return df
    for col in df.columns:
        series = df[col].astype("object")
        if series.map(lambda v: isinstance(v, str) and v.startswith("/Date(")).any():
            df[col] = series.map(
                lambda v: sap_odata_date_to_ddmmyyyy(v) if isinstance(v, str) else v
            )
    return df
