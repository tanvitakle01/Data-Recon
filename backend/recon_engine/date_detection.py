"""Deterministic, value-based date detection.

Whether a key pair is "the date one" — excluded from value-pairing and used
only for corroboration (see ``routes.value_mapping._split_date_pair``) — is
decided by looking at a cheap sample of the column's OWN VALUES: a
date-shaped regex pre-filter, then a real parse attempt via
``pandas.to_datetime``. Never a column-name guess (the column-name alias
tables that used to live in ``recon_engine.field_roles`` /
``lib/fieldRoleAliases.js`` are gone — nothing in this deploy infers a
business role from a header) and never an LLM call — this is a fixed-cost
check over a small sample, safe to run on every request.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

# Shaped like a date a real-world extract is likely to use: ISO
# date/datetime (2024-01-01[ 12:30[:00]]), dotted/slashed/dashed short-year
# or long-year (12.04.26, 04/12/2026, 12-04-26), or year-first slash/dot
# (2026/04/12). Deliberately does NOT match a bare run of digits (e.g. a
# plain numeric ID like "12345") — a date needs at least one separator.
_DATE_LIKE_PATTERN = re.compile(
    r"""^\s*(
        \d{4}-\d{1,2}-\d{1,2}([ T]\d{1,2}:\d{2}(:\d{2})?)?
        |\d{1,2}[./-]\d{1,2}[./-]\d{2,4}
        |\d{4}[./]\d{1,2}[./]\d{1,2}
    )\s*$""",
    re.VERBOSE,
)

_DEFAULT_SAMPLE_SIZE = 20
_DEFAULT_HIT_THRESHOLD = 0.8


def is_date_like_series(
    series: pd.Series | None,
    sample_size: int = _DEFAULT_SAMPLE_SIZE,
    hit_threshold: float = _DEFAULT_HIT_THRESHOLD,
) -> bool:
    """True when at least ``hit_threshold`` of a ``sample_size`` sample of
    ``series``'s non-null values are date-shaped (regex) AND parse cleanly
    via :func:`pandas.to_datetime`.

    A cheap, deterministic value-based check — never a guess from the
    column's name, never an LLM call. ``None``/empty/all-null input is "no
    signal", not a false positive: returns ``False``.
    """
    if series is None:
        return False
    sample = series.dropna().astype(str).head(sample_size)
    if sample.empty:
        return False
    shaped = sample[sample.map(lambda v: bool(_DATE_LIKE_PATTERN.match(v)))]
    if shaped.empty:
        return False
    parsed = pd.to_datetime(shaped, errors="coerce", format="mixed")
    hit_rate = parsed.notna().sum() / len(sample)
    return bool(hit_rate >= hit_threshold)


# ── format identification ────────────────────────────────────────────────────
# Distinct from ``is_date_like_series`` (which only answers "is this a date
# column"): this identifies WHICH textual format a date column actually uses —
# component order, separator, zero-padding, year width — purely from the
# column's own sampled values. Never a column-name guess, never an LLM call,
# never a hardcoded assumption about what format "should" be used; the whole
# point is that two datasets reconciled against each other are never assumed
# to share a date convention (ISO vs "M/D/YYYY" vs "DD.MM.YYYY", padded vs
# not, 2- vs 4-digit year) — each side's actual format is read off its data.
_COMPONENT_PATTERN = re.compile(r"^(\d{1,4})([./-])(\d{1,4})\2(\d{1,4})$")


@dataclass(frozen=True)
class DateFormatSpec:
    """A best-effort description of a date column's own textual format.

    ``order`` is the left-to-right sequence of components as they appear in
    the text — e.g. ``("Y", "M", "D")`` for ISO ``2026-09-04``, ``("M", "D",
    "Y")`` for ``9/4/2026``. ``separator`` is the literal character between
    components (real-world extracts don't mix separators within one date
    column). ``zero_padded`` is False for ``9/4/2026`` (no leading zero),
    True for ``09/04/2026``. ``year_digits`` is 2 or 4.

    ``ambiguous`` is True when the day/month order could not be read off the
    data itself — every sampled value has both candidate components <= 12
    (e.g. a column containing only "9/4/2026"-shaped values, or a single
    repeated date). ``order`` still carries a filled-in month-first default
    in that case (matching pandas'/dateutil's own default convention), but
    callers must not present it as a confident finding — surface the
    ambiguity rather than silently trusting the guess.
    """

    order: tuple[str, str, str]
    separator: str
    zero_padded: bool
    year_digits: int
    ambiguous: bool

    def display(self) -> str:
        """A short human-readable token string for UI/logging, e.g.
        ``"M/D/YYYY"`` or ``"DD.MM.YYYY"``. Informational only — NOT the same
        token vocabulary ``ops.format_to_strftime`` consumes today (which can
        only emit zero-padded month/day on output; an unpadded spec like this
        one can't yet be authored as a ``date_parse``/``date_format``
        ``canonical_format`` string without that op gaining unpadded tokens).
        """
        tokens = {
            "Y": "Y" * self.year_digits,
            "M": "MM" if self.zero_padded else "M",
            "D": "DD" if self.zero_padded else "D",
        }
        return self.separator.join(tokens[c] for c in self.order)


def strip_time_suffix(value: str) -> str:
    """Drop an optional trailing time-of-day (``" 12:30[:00]"``/``"T12:30..."``)
    off a date-like string, and surrounding whitespace. Shared with
    ``key_normalization`` so a detected format's separator/order is
    applied to the same date-only text it was inferred from."""
    return value.split("T")[0].split(" ")[0].strip()


_STRFTIME_TOKEN = {"Y4": "%Y", "Y2": "%y", "M": "%m", "D": "%d"}


def strftime_format(spec: DateFormatSpec) -> str:
    """The ``strftime`` format string ``spec`` describes, e.g. ``"%m.%d.%Y"``.

    Exposed so a caller that has to parse the SAME column more than once (see
    ``key_normalization.fit_key_canonicalizer``) can detect the format once and
    reuse it, instead of re-detecting it from whatever rows it happens to hold
    the second time.
    """
    year_token = _STRFTIME_TOKEN["Y4" if spec.year_digits == 4 else "Y2"]
    tokens = {"Y": year_token, "M": _STRFTIME_TOKEN["M"], "D": _STRFTIME_TOKEN["D"]}
    return spec.separator.join(tokens[c] for c in spec.order)


def parse_with_format(series: pd.Series, fmt: str | None) -> pd.Series:
    """Parse ``series`` with ``fmt``, or with a mixed parse when ``fmt`` is
    ``None`` (the column was date-like but no component order could be read
    off it). Unparseable values become ``NaT``."""
    if series is None or len(series) == 0:
        return pd.Series([], dtype="datetime64[ns]")
    if fmt is None:
        return pd.to_datetime(series, errors="coerce", format="mixed")
    stripped = series.astype(str).map(strip_time_suffix)
    return pd.to_datetime(stripped, format=fmt, errors="coerce")


def parse_date_series(series: pd.Series | None) -> pd.Series:
    """Parse ``series`` into ``pandas`` datetimes using ITS OWN detected
    format (:func:`detect_date_format`) — never a hardcoded/assumed format,
    never the other side's format.

    One explicit ``strftime`` format is applied to every value in the column
    (never ``format="mixed"``, which infers day/month order per value and can
    assign a different order to different rows of the SAME ambiguous column —
    see :func:`detect_date_format`'s docstring). Falls back to a mixed parse
    only when the column doesn't clear the date-like bar strongly enough for
    :func:`detect_date_format` to read a component order off it at all
    (``spec is None`` — distinct from ``spec.ambiguous``, which still yields a
    usable, if unconfident, format). Returns an all-``NaT`` series, preserving
    ``series``'s index, when ``series`` isn't date-like at all.

    Shared by ``key_normalization`` (join-key canonicalization) and
    ``engine.anchor_inference`` (recovering a run's anchor date from a frozen
    target extract) so a date column is parsed exactly the same way, off its
    own values, everywhere in the engine that needs to.
    """
    if series is None or series.empty:
        return series if series is not None else pd.Series([], dtype="datetime64[ns]")
    if not is_date_like_series(series):
        return pd.Series([pd.NaT] * len(series), index=series.index, dtype="datetime64[ns]")
    spec = detect_date_format(series)
    return parse_with_format(series, strftime_format(spec) if spec is not None else None)


def detect_date_format(
    series: pd.Series | None,
    sample_size: int = _DEFAULT_SAMPLE_SIZE,
    hit_threshold: float = _DEFAULT_HIT_THRESHOLD,
) -> DateFormatSpec | None:
    """Infer ``series``'s own date format from its values, or ``None`` when
    the column isn't date-like enough to bother (same gate as
    :func:`is_date_like_series`, same ``sample_size``/``hit_threshold``).

    Deterministic and value-based only: a date-shaped regex splits each
    sampled value into its three numeric components, then
      * a leading 4-digit group is the year, and the remaining two are
        assumed Y-M-D (ISO order) — a year-first-but-day-before-month export
        is not a real-world convention worth defaulting to, so this case is
        never marked ambiguous;
      * otherwise the year is the trailing group, and whichever of the other
        two groups has a value > 12 in at least one sampled row is
        unambiguously the day (a month can never exceed 12) — the other is
        the month;
      * if neither ever exceeds 12 across the whole sample, the order can't
        be determined from the data alone; a month-first default is filled
        in but ``ambiguous`` is set so callers don't treat it as confident.
    """
    if not is_date_like_series(series, sample_size=sample_size, hit_threshold=hit_threshold):
        return None

    sample = series.dropna().astype(str).map(strip_time_suffix).head(sample_size)
    # Each entry is the 3 numeric components in text order (NOT including the
    # separator, captured into ``separator`` once below) — g[0]/g[1]/g[2].
    groups: list[tuple[str, str, str]] = []
    separator: str | None = None
    for value in sample:
        m = _COMPONENT_PATTERN.match(value)
        if m:
            if separator is None:
                separator = m.group(2)
            groups.append((m.group(1), m.group(3), m.group(4)))
    if not groups or separator is None:
        return None

    year_pos = 0 if all(len(g[0]) == 4 for g in groups) else 2
    year_digits = 4 if all(len(g[year_pos]) == 4 for g in groups) else 2
    other_positions = [p for p in (0, 1, 2) if p != year_pos]

    if year_pos == 0:
        # Year-first data in the wild is essentially always ISO order
        # (Y-M-D) — a Y-D-M export isn't a real convention worth defaulting
        # to, so this case is never ambiguous.
        month_pos, day_pos = other_positions[0], other_positions[1]
        ambiguous = False
    else:
        values_by_pos = {p: [int(g[p]) for g in groups] for p in other_positions}
        day_pos = next((p for p in other_positions if any(v > 12 for v in values_by_pos[p])), None)
        ambiguous = day_pos is None
        if ambiguous:
            # Month-first default (matches pandas'/dateutil's own default
            # dayfirst=False behaviour) — flagged, never presented as read
            # off the data.
            month_pos, day_pos = other_positions[0], other_positions[1]
        else:
            month_pos = next(p for p in other_positions if p != day_pos)

    order_by_pos = {year_pos: "Y", day_pos: "D", month_pos: "M"}
    order = tuple(order_by_pos[p] for p in (0, 1, 2))  # type: ignore[assignment]

    zero_padded = all(len(g[month_pos]) == 2 for g in groups) and all(len(g[day_pos]) == 2 for g in groups)

    return DateFormatSpec(
        order=order, separator=separator, zero_padded=zero_padded,
        year_digits=year_digits, ambiguous=ambiguous,
    )
