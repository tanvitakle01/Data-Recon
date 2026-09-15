"""Secret scrubbing for text that is about to be logged or returned.

:func:`mask_secrets` exists because an exception string from the ``openai`` SDK
can, in some failure modes, echo request material back at us — including, in
some SDK versions, the ``Authorization`` header it sent. The app authenticates
to Azure AI Foundry with an Azure AD bearer token, so that header is a live
credential: every path that turns a provider exception into text runs it
through here first, in every environment.
"""

from __future__ import annotations

import re

# What a redacted credential looks like everywhere it is displayed or logged.
_MASK = "***REDACTED***"

_BEARER_RE = re.compile(r"(?i)\bBearer\s+[\w\-.~+/]+=*")


def mask_secrets(text: str) -> str:
    """Redact any ``Bearer <token>`` from ``text``."""
    if not text:
        return text
    return _BEARER_RE.sub(f"Bearer {_MASK}", text)
