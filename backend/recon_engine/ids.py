"""Identity primitives for run/batch/record/mapping/pair traceability.

Two families, matching the two ways an id needs to behave:

* RANDOM (uuid7) — ``new_id()``. Every occurrence is genuinely new: batches,
  result records, LLM calls, error events. uuid7 is time-ordered, which gives
  better index locality than uuid4 on high-volume tables (``results`` detail
  rows in particular).
* DETERMINISTIC (uuid5) — :func:`field_mapping_id` / :func:`pair_id`. The same
  logical mapping/pair must produce the IDENTICAL id in every run, so it can
  be looked up rather than re-derived. Both are computed over a canonical,
  order-SENSITIVE key (source/target are fixed roles, never interchangeable —
  unlike :func:`canonical.canonical_column_key`'s order-independent column
  SET, this is the wrong shape to reuse here).

Deliberately independent of ``storage.attribute_mapping_store`` /
``storage.value_pair_store``, which keep their own established identity
scheme (random uuid4 id + dedup via a UNIQUE constraint). These ids exist
purely for result-row/batch/error traceability, not as a replacement for
those stores' primary keys.
"""

from __future__ import annotations

import uuid

# Frozen forever — changing this changes every previously computed
# field_mapping_id/pair_id. Generated once via uuid.uuid4(); never regenerate.
NAMESPACE = uuid.UUID("ec0e09ac-7119-4c37-b352-f29a817e6c66")

_UNIT_SEP = "\x1f"  # avoids ambiguity from values that contain a plain "-" or "|"


def new_id() -> str:
    """A fresh, time-ordered, globally-unique id (uuid7)."""
    return str(uuid.uuid7())


def _norm(value: object) -> str:
    """Trim + case-fold a single component before hashing.

    Same normalization idea as ``canonical._normalize_columns``, but applied
    to one fixed-position value rather than sorted across a set — order
    matters here (source vs. target are never interchangeable).
    """
    return str(value).strip().casefold()


def field_mapping_id(
    source_connector: str,
    target_connector: str,
    comparison_type: str,
    source_field: str,
    target_field: str,
) -> str:
    """Stable id for one (source_connector, target_connector, comparison_type,
    source_field, target_field) field mapping — identical across every run."""
    key = _UNIT_SEP.join(
        _norm(part)
        for part in (source_connector, target_connector, comparison_type, source_field, target_field)
    )
    return str(uuid.uuid5(NAMESPACE, key))


def pair_id(field_mapping_id_: str, source_value: object, target_value: object | None) -> str:
    """Stable id for one (field_mapping_id, source_value, target_value) value
    pair — identical across every run, including when the pair is supplied in
    a different batch order (canonicalization is per-value, not order-of-
    discovery dependent)."""
    key = _UNIT_SEP.join(
        [field_mapping_id_, _norm(source_value), _norm(target_value if target_value is not None else "")]
    )
    return str(uuid.uuid5(NAMESPACE, key))
