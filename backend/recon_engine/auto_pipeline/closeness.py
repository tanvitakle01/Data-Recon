"""Edit-distance ranking of a supplied value against a live options list.

Used by the Auto-mode error-resolver interrupts (see ``interrupts.py``) to turn
a wrong-but-close value (``ZOBP2408``) into ranked suggestions from the
connector's REAL live options (``ZOBP2508``, ...) — never an invented or
hardcoded guess list.

Hand-rolled Levenshtein rather than a dependency (neither ``rapidfuzz`` nor
``python-Levenshtein`` is installed): identifiers here (entity/field names,
planning-area codes) are short, so the O(n*m) DP cost is negligible, and
edit distance ranks a single wrong character (``ZOBP2408`` vs ``ZOBP2508``)
correctly where prefix/substring matching would not.
"""

from __future__ import annotations


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr[j] = min(
                prev[j] + 1,  # deletion
                curr[j - 1] + 1,  # insertion
                prev[j - 1] + cost,  # substitution
            )
        prev = curr
    return prev[-1]


def rank_closest(query: str, options: list[str], limit: int = 4) -> list[str]:
    """``options`` ranked by edit distance to ``query`` (closest first).

    Case-insensitive so a case-only difference never buries the real match.
    Ties are broken by option length then alphabetically, so the ranking is
    stable and deterministic across repeated calls (e.g. on re-ask).
    """
    q = (query or "").strip().lower()
    candidates = [opt for opt in options if opt]
    ranked = sorted(candidates, key=lambda opt: (_levenshtein(q, opt.strip().lower()), len(opt), opt))
    return ranked[: max(0, limit)]
