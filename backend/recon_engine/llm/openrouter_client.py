"""OpenRouter chat client that returns parsed JSON — failover tier 4 (last resort, free models).

Thin subclass of :class:`~backend.recon_engine.llm.openai_compatible.
OpenAICompatibleJSONClient`, calling OpenRouter's OpenAI-compatible endpoint.
The ``openai`` SDK is an optional dependency, imported lazily on first use by
the base class.
"""

from __future__ import annotations

from backend.recon_engine.config import get_settings
from backend.recon_engine.llm.openai_compatible import OpenAICompatibleJSONClient


class OpenRouterJSONClient(OpenAICompatibleJSONClient):
    """Minimal OpenRouter wrapper: messages in, parsed-JSON object out."""

    name = "openrouter"

    def __init__(self, *, api_key: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        super().__init__(
            api_key=api_key if api_key is not None else settings.openrouter.api_key,
            model=model or settings.openrouter.model,
            base_url=settings.openrouter.base_url,
            provider_label="OpenRouter",
            api_key_env="OPENROUTER_API_KEY",
            model_env="OPENROUTER_MODEL",
        )
