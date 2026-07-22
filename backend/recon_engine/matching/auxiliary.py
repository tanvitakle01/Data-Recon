"""MDT Auxiliary Field Recommender — matching-evidence fields for the
deterministic engine ONLY.

Beyond the primary Key/Compare fields (Material->PRDID, ProductionPlant->LOCID),
the product/location matchers gain accuracy from AUXILIARY evidence attributes:
a plant's ``LOCNAME`` often embeds the plant code, a product's ``PRODDESC`` /
``PRODGROUP`` support the description-bridge and group-validation rules, etc.

**These are matching-evidence ONLY.** They are consumed *inside* the matcher
functions and never enter ``business_key``, ``compare_fields``, the shadow
source, or reconciliation output. This module only *recommends* which real,
populated columns to feed the matchers — it never writes anything downstream.

The reference lists below are SEEDS, not an exhaustive/exact contract: real
schemas vary in naming, so existence is checked case-insensitively/normalized
(not exact-string), and a field at 0% fill is never recommended regardless of
tier. Tier 1 preferred; Tier 2 is the fall-through when Tier 1 is absent/empty.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd
from pydantic import BaseModel

from backend.recon_engine.engine.executor import _is_blank  # reuse the blank primitive

# ── roles ────────────────────────────────────────────────────────────────────
# A role is BOTH which matcher input a candidate feeds AND whether any current
# rule consumes it. "*_validation" roles are recommended/surfaced for
# transparency but have no rule wired to them yet (future enhancement) — they
# are tagged consumed=False so the UI never implies they affect matching.
ROLE_LOCATION_ALT_NAME = "location_alt_name"          # location Rule 2 (embedded-code)
ROLE_LOCATION_VALIDATION = "location_validation"      # not consumed yet
ROLE_PRODUCT_ALT_ID = "product_alt_id"                # product Rule 4
ROLE_PRODUCT_DESCRIPTION = "product_description"      # product Rule 5 (target side)
ROLE_PRODUCT_GROUP = "product_group"                  # product Rule 1 (group-validation)
ROLE_PRODUCT_VALIDATION = "product_validation"        # not consumed yet
ROLE_SOURCE_PRODUCT_DESCRIPTION = "source_product_description"  # product Rule 5 (source side)
ROLE_SOURCE_MATERIAL_GROUP = "source_material_group"  # product Rule 0/1
ROLE_SOURCE_PRODUCT_VALIDATION = "source_product_validation"    # not consumed yet
ROLE_SOURCE_PLANT_VALIDATION = "source_plant_validation"        # not consumed yet

_CONSUMED_ROLES = frozenset(
    {
        ROLE_LOCATION_ALT_NAME,
        ROLE_PRODUCT_ALT_ID,
        ROLE_PRODUCT_DESCRIPTION,
        ROLE_PRODUCT_GROUP,
        ROLE_SOURCE_PRODUCT_DESCRIPTION,
        ROLE_SOURCE_MATERIAL_GROUP,
    }
)


@dataclass(frozen=True)
class _Seed:
    name: str
    tier: int
    role: str


# ── seed reference lists (from the build spec's tables) ──────────────────────
# Primary keys (LOCID / PRDID / Material / ProductionPlant) are intentionally
# NOT here — they are the primary fields, not auxiliary evidence.

TARGET_LOCATION_SEEDS: tuple[_Seed, ...] = (
    _Seed("LOCNAME", 1, ROLE_LOCATION_ALT_NAME),
    _Seed("LOCDESCRDEM", 1, ROLE_LOCATION_ALT_NAME),
    _Seed("LOCATIONTYPE", 1, ROLE_LOCATION_VALIDATION),
    _Seed("LOCTYPEDEM", 1, ROLE_LOCATION_VALIDATION),
    _Seed("LOCCOUNTRY", 1, ROLE_LOCATION_VALIDATION),
    _Seed("LOCIDDEM", 2, ROLE_LOCATION_VALIDATION),
    _Seed("LOCATIONREGION", 2, ROLE_LOCATION_VALIDATION),
    _Seed("LOCCITY", 2, ROLE_LOCATION_VALIDATION),
    _Seed("LOCTIMEZONE", 2, ROLE_LOCATION_VALIDATION),
    _Seed("SOURCELOCATIONTZ", 2, ROLE_LOCATION_VALIDATION),
)

TARGET_PRODUCT_SEEDS: tuple[_Seed, ...] = (
    _Seed("PRODDESC", 1, ROLE_PRODUCT_DESCRIPTION),
    _Seed("PRODDESCDEM", 1, ROLE_PRODUCT_DESCRIPTION),
    _Seed("PRODGROUP", 1, ROLE_PRODUCT_GROUP),
    _Seed("PRODTYPE", 1, ROLE_PRODUCT_VALIDATION),
    _Seed("PRDIDDEM", 1, ROLE_PRODUCT_ALT_ID),
    _Seed("PRODGROUPDEM", 2, ROLE_PRODUCT_GROUP),
    _Seed("PRODTYPEDEM", 2, ROLE_PRODUCT_VALIDATION),
    _Seed("SPRDID", 2, ROLE_PRODUCT_ALT_ID),
    _Seed("SPRODDESC", 2, ROLE_PRODUCT_DESCRIPTION),
    _Seed("SPRODGROUP", 2, ROLE_PRODUCT_VALIDATION),
    _Seed("SPRODTYPE", 2, ROLE_PRODUCT_VALIDATION),
)

SOURCE_PRODUCT_SEEDS: tuple[_Seed, ...] = (
    _Seed("SalesOrderItemText", 1, ROLE_SOURCE_PRODUCT_DESCRIPTION),
    _Seed("MaterialGroup", 1, ROLE_SOURCE_MATERIAL_GROUP),
    _Seed("MaterialPricingGroup", 2, ROLE_SOURCE_PRODUCT_VALIDATION),
    _Seed("AdditionalMaterialGroup1", 2, ROLE_SOURCE_PRODUCT_VALIDATION),
    _Seed("AdditionalMaterialGroup2", 2, ROLE_SOURCE_PRODUCT_VALIDATION),
    _Seed("AdditionalMaterialGroup3", 2, ROLE_SOURCE_PRODUCT_VALIDATION),
    _Seed("AdditionalMaterialGroup4", 2, ROLE_SOURCE_PRODUCT_VALIDATION),
    _Seed("AdditionalMaterialGroup5", 2, ROLE_SOURCE_PRODUCT_VALIDATION),
)

SOURCE_PLANT_SEEDS: tuple[_Seed, ...] = (
    # OriginalPlant was too sparse to rely on at design time — the population
    # check re-verifies its fill rate per dataset rather than assuming.
    _Seed("OriginalPlant", 2, ROLE_SOURCE_PLANT_VALIDATION),
)


class AuxiliaryFieldCandidate(BaseModel):
    """One evaluated auxiliary attribute — surfaced to the UI and (when
    confirmed + consumed) fed to the matcher."""

    seed_name: str            # the reference-list attribute name
    resolved_name: str | None  # the real column it matched (fuzzy), or None
    tier: int
    role: str
    confirmed_existing: bool
    confirmed_populated: bool
    fill_rate: float | None    # 0..1 fraction of non-blank rows (None if absent)
    consumed: bool             # does a current matcher rule actually use it?

    @property
    def confirmed(self) -> bool:
        return self.confirmed_existing and self.confirmed_populated


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _fill_rate(series: pd.Series) -> float:
    """Fraction of non-blank rows (uses ``_is_blank`` — stricter than notna:
    ``""``/whitespace/"nan"/"NaT" count as blank)."""
    if len(series) == 0:
        return 0.0
    return float(1.0 - series.map(_is_blank).mean())


def recommend_auxiliary_fields(
    df: pd.DataFrame, seeds: tuple[_Seed, ...]
) -> list[AuxiliaryFieldCandidate]:
    """Evaluate every seed against ``df``: fuzzy existence + population check.

    Returns ALL evaluated seeds (existing/absent, populated/empty) so the caller
    can both feed the matcher (``.confirmed`` ones) and report the full picture.
    Order follows the seed list, i.e. Tier 1 before Tier 2 within each role —
    so filtering a role yields a tier-ranked list, giving Tier-2 fall-through
    for free when a Tier-1 field is absent or empty.
    """
    colmap: dict[str, str] = {}
    for col in df.columns:
        colmap.setdefault(_norm(col), str(col))  # first-wins on collision

    out: list[AuxiliaryFieldCandidate] = []
    for seed in seeds:
        resolved = colmap.get(_norm(seed.name))
        exists = resolved is not None
        rate = _fill_rate(df[resolved]) if exists else None
        populated = bool(exists and rate is not None and rate > 0.0)
        out.append(
            AuxiliaryFieldCandidate(
                seed_name=seed.name,
                resolved_name=resolved,
                tier=seed.tier,
                role=seed.role,
                confirmed_existing=exists,
                confirmed_populated=populated,
                fill_rate=rate,
                consumed=seed.role in _CONSUMED_ROLES,
            )
        )
    return out


def evaluate_side(df: pd.DataFrame, side: str) -> dict[str, list[dict]]:
    """Grouped, JSON-ready recommender output for ONE dataset side.

    ``side="source"`` evaluates the S/4 seed groups (``source_product`` /
    ``source_plant``); ``side="target"`` evaluates the IBP seed groups
    (``target_product`` / ``target_location``). The shape mirrors the
    ``auxiliary_fields`` block that ``/value-mapping/run`` returns, so the same
    "Recommended for Deterministic Mapping" panel can render straight off a
    connector fetch response. Evidence-only — this only reports fill rates; it
    never promotes a column into the mapping.
    """
    if side == "source":
        groups = {"source_product": SOURCE_PRODUCT_SEEDS, "source_plant": SOURCE_PLANT_SEEDS}
    elif side == "target":
        groups = {"target_product": TARGET_PRODUCT_SEEDS, "target_location": TARGET_LOCATION_SEEDS}
    else:
        return {}
    return {
        key: [c.model_dump(mode="json") for c in recommend_auxiliary_fields(df, seeds)]
        for key, seeds in groups.items()
    }


def confirmed_series(
    df: pd.DataFrame,
    recommendations: list[AuxiliaryFieldCandidate],
    role: str,
) -> list[pd.Series]:
    """Tier-ranked list of live Series for the confirmed candidates of a role.

    Each Series carries its resolved column name via ``.name`` so the matcher
    can cite which field an evidence match came from.
    """
    series: list[pd.Series] = []
    for rec in recommendations:
        if rec.role == role and rec.confirmed and rec.resolved_name:
            series.append(df[rec.resolved_name])
    return series


def first_confirmed_series(
    df: pd.DataFrame,
    recommendations: list[AuxiliaryFieldCandidate],
    role: str,
) -> pd.Series | None:
    """The single best (highest-tier) confirmed Series for a role, or None."""
    picks = confirmed_series(df, recommendations, role)
    return picks[0] if picks else None
