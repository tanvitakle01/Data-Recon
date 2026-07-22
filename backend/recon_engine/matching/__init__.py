"""Deterministic tiered value matchers for identifier resolution.

This is the "(B) VALUE MAPPING" concern (see the Rules-step re-engineering
notes): resolving SAP identifier values against IBP identifier values,
discovered from data with confidence + evidence — never guessed by an LLM.
See ``product.match_products`` and ``location.match_locations``.
"""

from backend.recon_engine.matching.auxiliary import (
    SOURCE_PLANT_SEEDS,
    SOURCE_PRODUCT_SEEDS,
    TARGET_LOCATION_SEEDS,
    TARGET_PRODUCT_SEEDS,
    AuxiliaryFieldCandidate,
    confirmed_series,
    evaluate_side,
    first_confirmed_series,
    recommend_auxiliary_fields,
)
from backend.recon_engine.matching.location import match_locations
from backend.recon_engine.matching.product import match_products

__all__ = [
    "match_locations",
    "match_products",
    "AuxiliaryFieldCandidate",
    "recommend_auxiliary_fields",
    "evaluate_side",
    "confirmed_series",
    "first_confirmed_series",
    "TARGET_LOCATION_SEEDS",
    "TARGET_PRODUCT_SEEDS",
    "SOURCE_PRODUCT_SEEDS",
    "SOURCE_PLANT_SEEDS",
]
