"""Connections page — session-scoped LLM endpoint override.

Lets a user point the app's LLM calls at their own billing plan by supplying
their own API key (and, optionally, their own base URL) for the length of a
browser session. Four endpoints, all operating on in-process memory only:

``GET    /api/connections/status``    what is active right now (never the key)
``POST   /api/connections/test``      probe credentials, store nothing
``POST   /api/connections/override``  probe, then store on success only
``DELETE /api/connections/override``  drop the override, revert to default

The provider call for "Test connection" is made **here, server-side** — the
browser never talks to the provider directly, so the key never needs a
CORS-exposed path out of client JS, and it exists in the browser only for the
moment between typing and submitting.

Security invariants for this module:

* The raw key is accepted in a request body, handed to
  :mod:`~backend.recon_engine.llm.session_override`, and never echoed. Every
  response shape below carries at most ``key_suffix`` (4 characters).
* No route here writes to a store, a file, or a log line containing the key.
  Provider errors are surfaced through
  :func:`~backend.recon_engine.llm.session_override.mask_secrets`.
* ``backend/main.py``'s 422 diagnostic handler, which logs raw request bodies
  app-wide, explicitly skips this prefix — see ``_BODY_LOG_DENYLIST`` there.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.recon_engine.compiler.base import ContractCompilerError
from backend.recon_engine.config import get_settings
from backend.recon_engine.llm import session_override
from backend.recon_engine.llm.azure_foundry_client import AzureFoundryJSONClient
from backend.recon_engine.llm.errors import RetryableLLMError
from backend.recon_engine.llm.session_override import mask_secrets

logger = logging.getLogger("recon.connections")

router = APIRouter(prefix="/api/connections", tags=["connections"])

# The header the browser echoes its session token back on. Mirrored in
# frontend/src/services/api.js, which attaches it to every request.
SESSION_HEADER = "X-Recon-Session"


class OverrideRequest(BaseModel):
    """An override being tested or saved. ``base_url`` blank means "use the
    app's built-in endpoint" — the key is then used against
    ``AZURE_FOUNDRY_BASE_URL``."""

    api_key: str = Field(min_length=1)
    base_url: str | None = None


def _session_token(request: Request) -> str | None:
    return request.headers.get(SESSION_HEADER)


def _default_endpoint() -> dict[str, Any]:
    """What the page may say about the app's own connection: the model, and
    nothing else.

    The built-in endpoint's URL and auth mechanism are deliberately NOT
    disclosed — the model id is the only part a user needs in order to know
    what their key will be billed for. The base URL still resolves normally
    inside :func:`_probe` and ``build_llm_client``; it just never crosses the
    wire.
    """
    return {"model": get_settings().azure_foundry.model or None}


def _probe(api_key: str, base_url: str | None) -> tuple[bool, str | None]:
    """Run one minimal request against the endpoint. ``(ok, error_message)``.

    Never raises: a failed test is an inline "failed" on the page, not a 500.
    The model id is always the app's configured deployment — the user supplies
    billing credentials, not a different model.
    """
    settings = get_settings()
    resolved_base = (base_url or "").strip() or settings.azure_foundry.base_url
    if not resolved_base:
        return False, (
            "No base URL to test against: the app has no AZURE_FOUNDRY_BASE_URL "
            "configured, so a base URL must be supplied here."
        )
    if not settings.azure_foundry.model:
        return False, (
            "No model configured: set AZURE_FOUNDRY_MODEL on the server before "
            "using an override."
        )
    client = AzureFoundryJSONClient(api_key=api_key, base_url=resolved_base)
    try:
        client.probe()
    except (ContractCompilerError, RetryableLLMError) as exc:
        # Already masked by the client, masked again for belt and braces.
        return False, mask_secrets(str(exc))
    except Exception as exc:  # noqa: BLE001 - a test button must not 500
        return False, mask_secrets(f"{type(exc).__name__}: {exc}")
    return True, None


@router.get("/status")
async def connection_status(request: Request) -> dict[str, Any]:
    """What this session is currently using. Safe to call unauthenticated —
    it discloses the app's own endpoint and, at most, 4 characters of the
    user's key."""
    override = session_override.get(_session_token(request))
    default = _default_endpoint()
    if override is None:
        return {"active": False, "source": "default", "default": default}
    return {
        "active": True,
        "source": "override",
        "key_suffix": override.key_suffix,
        "masked_key": override.masked_key,
        # Only a base URL the USER supplied is echoed. A null here means the
        # override runs against the built-in endpoint, whose URL is not
        # disclosed — see _default_endpoint.
        "base_url": override.base_url,
        "model": default["model"],
        "default": default,
    }


@router.post("/test")
async def test_connection(payload: OverrideRequest) -> dict[str, Any]:
    """Probe credentials without storing anything, whatever the outcome."""
    ok, error = _probe(payload.api_key, payload.base_url)
    logger.info(
        "Connection test: ok=%s base_url=%s",
        ok,
        (payload.base_url or "").strip() or "app default",
    )
    return {"ok": ok, "error": error}


@router.post("/override")
async def save_override(payload: OverrideRequest, request: Request) -> dict[str, Any]:
    """Probe, then store on success only.

    The probe is repeated here rather than trusting the client's earlier
    "Test connection" — a UI that skipped the test, or a key that stopped
    working in between, must not end up stored. A failed probe returns 400 and
    leaves any existing override untouched.
    """
    ok, error = _probe(payload.api_key, payload.base_url)
    if not ok:
        raise HTTPException(status_code=400, detail=error or "Connection test failed.")

    # Replace rather than accumulate: saving again from the same session
    # retires the previous token.
    session_override.delete(_session_token(request))
    try:
        token, override = session_override.create(
            api_key=payload.api_key, base_url=payload.base_url
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    default = _default_endpoint()
    logger.info(
        "LLM session override stored: base_url=%s model=%s key=…%s",
        override.base_url or "app default",
        default["model"],
        override.key_suffix,
    )
    return {
        "session_token": token,
        "active": True,
        "source": "override",
        "key_suffix": override.key_suffix,
        "masked_key": override.masked_key,
        "base_url": override.base_url,
        "model": default["model"],
        "default": default,
    }


@router.delete("/override")
async def clear_override(request: Request) -> dict[str, Any]:
    """Drop the override and revert to the app's default endpoint."""
    removed = session_override.delete(_session_token(request))
    logger.info("LLM session override cleared (had one: %s)", removed)
    return {"active": False, "source": "default", "cleared": removed, "default": _default_endpoint()}
