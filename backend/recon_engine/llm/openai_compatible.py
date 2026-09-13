"""Generic OpenAI-compatible chat-completions client.

Azure AI Foundry publishes an OpenAI-compatible ``chat.completions.create``
endpoint, so this one implementation — parameterized by provider
label/api_key/model/base_url — serves it via the already-installed ``openai``
SDK. No provider-specific SDK, no provider-specific response parsing.
:class:`~backend.recon_engine.llm.azure_foundry_client.AzureFoundryJSONClient`
is a thin subclass of this. ``api_key`` may be a static string or (as Azure
Foundry does) a zero-arg callable the ``openai`` SDK calls to fetch a fresh
bearer token per request.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.recon_engine.compiler.base import ContractCompilerError
from backend.recon_engine.llm.base import extract_message_content, parse_json_payload
from backend.recon_engine.llm.errors import RetryableLLMError, is_retryable_exception

logger = logging.getLogger("recon.llm.openai_compatible")


class OpenAICompatibleJSONClient:
    """Minimal OpenAI-compatible wrapper: messages in, parsed-JSON object out.

    A subclass sets its own ``name`` class attribute (the provider tag used by
    the failover orchestrator and outcome reporting) and passes ``api_key``/
    ``model``/``base_url`` (read from settings at construction time) plus a
    human-readable ``provider_label`` and the env var name to mention in
    "not configured" errors.
    """

    name = "openai_compatible"

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str | None,
        base_url: str | None,
        provider_label: str,
        api_key_env: str,
        model_env: str,
        base_url_env: str = "",
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._provider_label = provider_label
        self._api_key_env = api_key_env
        self._model_env = model_env
        self._base_url_env = base_url_env
        self._client: Any = None  # lazily constructed openai.OpenAI()

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    @property
    def model(self) -> str | None:
        return self._model

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise ContractCompilerError(
                f"{self._api_key_env} is not set. The {self._provider_label} "
                f"provider requires it."
            )
        if not self._model:
            # No invented default model for this tier — fail loudly instead of
            # guessing a model name that may not exist or may be paid-only.
            raise ContractCompilerError(
                f"{self._model_env} is not set. The {self._provider_label} "
                f"provider requires a model id."
            )
        if not self._base_url and self._base_url_env:
            # No invented default endpoint for this tier either — fail loudly
            # rather than silently falling through to the openai SDK's own
            # default (openai.com), which would misroute every call.
            raise ContractCompilerError(
                f"{self._base_url_env} is not set. The {self._provider_label} "
                f"provider requires a base URL."
            )
        try:
            from openai import OpenAI  # type: ignore
        except ModuleNotFoundError as exc:  # pragma: no cover - optional dep
            raise ContractCompilerError(
                "The 'openai' package is not installed. Run `pip install openai` "
                f"to enable the {self._provider_label} provider."
            ) from exc
        kwargs: dict[str, Any] = {"api_key": self._api_key}
        if self._base_url:
            kwargs["base_url"] = self._base_url
        self._client = OpenAI(**kwargs)
        return self._client

    def _create_completion(self, client: Any, messages: list[dict[str, str]]) -> Any:
        """Call chat completions at temperature 0, preferring JSON mode."""
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
        unavailable/connection failure (so the orchestrator can fail over),
        and :class:`ContractCompilerError` on any other failure or an
        unparseable response.
        """
        logger.info(
            "Calling %s: model=%s base_url=%s",
            self._provider_label, self._model, self._base_url or "default",
        )
        client = self._get_client()
        try:
            response = self._create_completion(client, messages)
        except ContractCompilerError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalise/classify all API failures
            logger.exception("%s API call failed", self._provider_label)
            if is_retryable_exception(exc):
                raise RetryableLLMError(
                    f"{self._provider_label} API call failed: {exc}", provider=self.name
                ) from exc
            raise ContractCompilerError(f"{self._provider_label} API call failed: {exc}") from exc

        content = extract_message_content(response, provider=self._provider_label)
        payload = parse_json_payload(content, provider=self._provider_label)
        logger.info("%s call succeeded: model=%s", self._provider_label, self._model)
        return payload
