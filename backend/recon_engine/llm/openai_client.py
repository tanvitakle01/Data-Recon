"""OpenAI chat client that returns parsed JSON.

Thin subclass of :class:`~backend.recon_engine.llm.openai_compatible.
OpenAICompatibleJSONClient`. No longer part of the default
``build_llm_client()`` failover chain (see :mod:`backend.recon_engine.llm.
failover`, which is Groq → Gemini → Cerebras → OpenRouter) — kept for
standalone/manual construction. The ``openai`` SDK is an optional dependency,
imported lazily on first use by the base class.
"""

from __future__ import annotations

from backend.recon_engine.config import get_settings
from backend.recon_engine.llm.openai_compatible import OpenAICompatibleJSONClient


class OpenAIJSONClient(OpenAICompatibleJSONClient):
    """Minimal OpenAI wrapper: messages in, parsed-JSON object out."""

    name = "openai"

    def __init__(self, *, api_key: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        super().__init__(
            api_key=api_key if api_key is not None else settings.openai.api_key,
            model=model or settings.openai.model,
            base_url=settings.openai.base_url,
            provider_label="OpenAI",
            api_key_env="OPENAI_API_KEY",
            model_env="OPENAI_MODEL",
        )
