"""Session-scoped LLM endpoint override — in-process memory only.

A user can supply their own API key (and optionally their own base URL) on the
**Connections** page to run the app's LLM calls against their own billing plan
instead of the app's Azure-AD-authenticated Azure AI Foundry deployment. That
override is deliberately the *weakest* kind of state this codebase holds:

* It lives in this module's ``_SESSIONS`` dict and nowhere else — never a
  database, never a file, never a log line, never an env var. Restarting the
  backend loses every override, which matches the rest of Stage-1's
  process-memory-only design (see ``SETUP.md``).
* The browser holds its session token in a JavaScript variable, not
  ``localStorage``/``sessionStorage``/a cookie, so a page refresh drops the
  token and the app reverts to the default endpoint. The orphaned server-side
  entry then ages out via :data:`_TTL_SECONDS`.
* The raw key is never returned to the client once stored. Only
  :attr:`LLMOverride.key_suffix` — the trailing 4 characters — ever goes back
  over the wire, so the Connections page can show ``••••••••ab12`` without the
  full value existing anywhere outside this process.

Two layers, mirroring ``call_context.py``'s ContextVar pattern:

``_SESSIONS``          token -> override, shared across requests (the store).
``_CURRENT_OVERRIDE``  the override resolved for *this* request, set once by
                       the middleware in ``backend/main.py`` so
                       :func:`~backend.recon_engine.llm.failover.build_llm_client`
                       can read it without every LLM call site threading a
                       request object down the stack.

:func:`mask_secrets` exists because an exception string from the ``openai`` SDK
can, in some failure modes, echo request material back at us. Every live key is
scrubbed from error text before it reaches a log or an HTTP response.
"""

from __future__ import annotations

import contextvars
import re
import secrets
import threading
import time
from dataclasses import dataclass

# Idle lifetime of a stored override. Long enough that a working session never
# has its key expire out from under it, short enough that tokens orphaned by a
# page refresh don't accumulate for the life of the process. Sliding: every
# successful lookup refreshes it.
_TTL_SECONDS = 8 * 60 * 60

# Shortest key we will store. Not a format check (providers differ) — just a
# guard against storing something that is obviously not a key.
_MIN_KEY_LENGTH = 8

# What a masked key looks like everywhere it is displayed or logged.
_MASK = "***REDACTED***"


@dataclass(frozen=True)
class LLMOverride:
    """One session's endpoint override. ``api_key`` never leaves this process."""

    api_key: str
    base_url: str | None  # None => fall back to AZURE_FOUNDRY_BASE_URL
    key_suffix: str  # trailing 4 chars, the only part safe to display

    @property
    def masked_key(self) -> str:
        return f"{'•' * 8}{self.key_suffix}"


# ── the store (process-wide, shared across requests) ─────────────────────────
_SESSIONS: dict[str, tuple[LLMOverride, float]] = {}
_LOCK = threading.Lock()


def _sweep(now: float) -> None:
    """Drop expired entries. Caller holds ``_LOCK``."""
    stale = [tok for tok, (_, seen) in _SESSIONS.items() if now - seen > _TTL_SECONDS]
    for tok in stale:
        del _SESSIONS[tok]


def create(*, api_key: str, base_url: str | None) -> tuple[str, LLMOverride]:
    """Store an override and return ``(session_token, override)``.

    The token is the client's only handle on the stored key — it is not derived
    from the key, so holding it grants use of the key but never reveals it.
    """
    key = (api_key or "").strip()
    if len(key) < _MIN_KEY_LENGTH:
        raise ValueError("API key is too short to be valid.")
    url = (base_url or "").strip() or None

    override = LLMOverride(api_key=key, base_url=url, key_suffix=key[-4:])
    token = secrets.token_urlsafe(32)
    now = time.monotonic()
    with _LOCK:
        _sweep(now)
        _SESSIONS[token] = (override, now)
    return token, override


def get(token: str | None) -> LLMOverride | None:
    """Look up an override by token, refreshing its idle timer."""
    if not token:
        return None
    now = time.monotonic()
    with _LOCK:
        _sweep(now)
        entry = _SESSIONS.get(token)
        if entry is None:
            return None
        override, _ = entry
        _SESSIONS[token] = (override, now)  # sliding TTL
        return override


def delete(token: str | None) -> bool:
    """Remove an override. Returns whether there was one to remove."""
    if not token:
        return False
    with _LOCK:
        return _SESSIONS.pop(token, None) is not None


def clear_all() -> None:
    """Drop every stored override (used by tests)."""
    with _LOCK:
        _SESSIONS.clear()


# ── request-scoped resolution (set by the middleware in backend/main.py) ─────
_CURRENT_OVERRIDE: contextvars.ContextVar[LLMOverride | None] = contextvars.ContextVar(
    "recon_llm_session_override", default=None
)


def set_request_override(override: LLMOverride | None) -> contextvars.Token:
    """Bind an override to the current request context."""
    return _CURRENT_OVERRIDE.set(override)


def reset_request_override(token: contextvars.Token) -> None:
    """Undo :func:`set_request_override` (call in the middleware's ``finally``)."""
    _CURRENT_OVERRIDE.reset(token)


def get_request_override() -> LLMOverride | None:
    """The override for this request, or ``None`` to use the app default."""
    return _CURRENT_OVERRIDE.get()


# ── secret scrubbing ─────────────────────────────────────────────────────────
def mask_secrets(text: str) -> str:
    """Redact every live session key from ``text``.

    Applied to exception text before it is logged or returned, because a
    provider SDK's error string can carry request material (including, in some
    SDK versions, an echoed ``Authorization`` header). Also catches a bare
    ``Bearer <token>`` so a key that never reached this store — the Azure AD
    token, say — cannot leak either.
    """
    if not text:
        return text
    with _LOCK:
        keys = [override.api_key for override, _ in _SESSIONS.values()]
    for key in keys:
        if key:
            text = text.replace(key, _MASK)
    return re.sub(r"(?i)\bBearer\s+[\w\-.~+/]+=*", f"Bearer {_MASK}", text)
