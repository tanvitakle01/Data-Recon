"""Deterministic tiered value matchers for identifier resolution.

This is the "(B) VALUE MAPPING" concern (see the Rules-step re-engineering
notes): resolving SAP identifier values against IBP identifier values,
discovered from data with confidence + evidence — never guessed by an LLM.
See ``product.match_products`` and ``location.match_locations``.
"""

from backend.recon_engine.matching.location import match_locations
from backend.recon_engine.matching.product import match_products

__all__ = ["match_locations", "match_products"]
