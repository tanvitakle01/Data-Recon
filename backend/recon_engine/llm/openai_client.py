"""OpenAI chat client that returns parsed JSON — the failover provider.

Mirrors :class:`~backend.recon_engine.compiler.groq_client.GroqJSONClient`
exactly (same ``complete_json(messages)`` surface, temperature-0 JSON-mode
completions with a graceful retry when ``response_format`` is unsupported), so
the failover orchestrator can treat Groq and OpenAI interchangeably. The
``openai`` SDK is an optional dependency, imported lazily on first use.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.recon_engine.compiler.base import ContractCompilerError
from backend.recon_engine.config import get_settings
from backend.recon_engine.llm.base import extract_message_content, parse_json_payload
from backend.recon_engine.llm.errors import RetryableLLMError, is_retryable_exception

logger = logging.getLogger("recon.llm.openai")


class OpenAIJSONClient:
    """Minimal OpenAI wrapper: messages in, parsed-JSON object out."""

    name = "openai"

    def __init__(self, *, api_key: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self._api_key = api_key if api_key is not None else settings.openai.api_key
        self._model = model or settings.openai.model
        self._base_url = settings.openai.base_url
        self._client: Any = None  # lazily constructed openai.OpenAI()

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    @property
    def model(self) -> str:
        return self._model

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise ContractCompilerError(
                "OPENAI_API_KEY is not set. The OpenAI fallback requires it. "
                "Set OPENAI_API_KEY (and optionally OPENAI_MODEL/OPENAI_BASE_URL)."
            )
        try:
            from openai import OpenAI  # type: ignore
        except ModuleNotFoundError as exc:  # pragma: no cover - optional dep
            raise ContractCompilerError(
                "The 'openai' package is not installed. Run `pip install openai` to "
                "enable the OpenAI fallback provider."
            ) from exc
        kwargs: dict[str, Any] = {"api_key": self._api_key}
        if self._base_url:
            kwargs["base_url"] = self._base_url
        self._client = OpenAI(**kwargs)
        return self._client

    def _create_completion(self, client: Any, messages: list[dict[str, str]]) -> Any:
        """Call OpenAI chat completions at temperature 0, preferring JSON mode."""
        base_kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": 0,
        }
        try:
            return client.chat.completions.create(
                response_format={"type": "json_object"}, **base_kwargs
            )
        except TypeError:
            return client.chat.completions.create(**base_kwargs)
        except Exception as exc:  # noqa: BLE001 - only swallowed to retry once
            if "response_format" in str(exc).lower():
                return client.chat.completions.create(**base_kwargs)
            raise

    def complete_json(self, messages: list[dict[str, str]]) -> Any:
        """Run one completion and return the parsed JSON payload.

        Raises :class:`RetryableLLMError` on a rate-limit/quota/timeout/
        unavailable/connection failure (so the orchestrator can stop failing
        over), and :class:`ContractCompilerError` on any other failure or an
        unparseable response.
        """
        logger.info("Calling OpenAI: model=%s base_url=%s", self._model, self._base_url or "default")
        client = self._get_client()
        try:
            response = self._create_completion(client, messages)
        except ContractCompilerError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalise/classify all API failures
            logger.exception("OpenAI API call failed")
            if is_retryable_exception(exc):
                raise RetryableLLMError(
                    f"OpenAI API call failed: {exc}", provider=self.name
                ) from exc
            raise ContractCompilerError(f"OpenAI API call failed: {exc}") from exc

        content = extract_message_content(response, provider="OpenAI")
        payload = parse_json_payload(content, provider="OpenAI")
        logger.info("OpenAI call succeeded: model=%s", self._model)
        return payload
