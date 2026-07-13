"""Contract validation gates.

* Gate 1 (structural) — schema, allow-listed operations, valid params, and
  field references checked against the *real* source/target schemas.
* Gate 2 (sample replay) — execute the contract on a 50-100 row sample and
  sanity-check the outcome.

Both must pass before a contract can be approved.
"""

from backend.recon_engine.validation.gate1_structural import (
    Gate1Report,
    validate_structural,
)
from backend.recon_engine.validation.gate2_replay import Gate2Report, replay_sample

__all__ = [
    "Gate1Report",
    "Gate2Report",
    "replay_sample",
    "validate_structural",
]
