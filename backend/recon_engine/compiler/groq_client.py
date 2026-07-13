"""Shared Groq chat client that returns parsed JSON.

Used by both the contract compiler (``groq_compiler``) and the transformation
script generator (``scripting/generator``). Handles the client lifecycle,
temperature-0 JSON-mode completions with SDK/API fallbacks, response-shape
errors, and code-fence stripping. The Groq SDK stays an optional dependency —
it is imported lazily on first use.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.recon_engine.compiler.base import ContractCompilerError
from backend.recon_engine.config import get_settings
from backend.recon_engine.llm.errors import RetryableLLMError, is_retryable_exception

logger = logging.getLogger("recon.compiler.groq")

_truststore_injected = False


def _ensure_os_trust_store() -> None:
    """Make outbound TLS trust the OS certificate store, once per process.

    On machines behind a TLS-inspecting corporate proxy, the proxy re-signs
    ``api.groq.com`` with an internal root CA that Windows already trusts but
    that Python's bundled ``certifi`` store does not — every Groq call then
    fails with ``CERTIFICATE_VERIFY_FAILED: self-signed certificate in
    certificate chain``, indistinguishable at the call site from a genuine
    outage. ``truststore`` is optional; if it isn't installed we log once and
    proceed with the default (certifi) trust store.
    """
    global _truststore_injected
    if _truststore_injected:
        return
    try:
        import truststore
    except ModuleNotFoundError:
        logger.warning(
            "The 'truststore' package is not installed; Groq calls will use "
            "certifi's trust store, which will fail on a TLS-inspecting "
            "corporate proxy. Run `pip install truststore` to fix this."
        )
        _truststore_injected = True  # don't retry the import every call
        return
    truststore.inject_into_ssl()
    _truststore_injected = True


class GroqJSONClient:
    """Minimal Groq wrapper: messages in, parsed-JSON object out."""

    name = "groq"

    def __init__(self, *, api_key: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self._api_key = api_key if api_key is not None else settings.groq.api_key
        self._model = model or settings.groq.model
        self._base_url = settings.groq.base_url
        self._client: Any = None  # lazily constructed groq.Groq()

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    @property
    def model(self) -> str:
        return self._model

    def _get_client(self) -> Any:
        """Lazily construct the Groq SDK client.

        The ``groq`` package is an optional dependency; importing lazily keeps
        the whole app runnable without it installed.
        """
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise ContractCompilerError(
                "GROQ_API_KEY is not set. The Groq compile phase requires it. "
                "Set GROQ_API_KEY (and optionally GROQ_MODEL/GROQ_BASE_URL), or use "
                "the deterministic fallback."
            )
        try:
            from groq import Groq  # type: ignore
        except ModuleNotFoundError as exc:  # pragma: no cover - optional dep
            raise ContractCompilerError(
                "The 'groq' package is not installed. Run `pip install groq` to enable "
                "the Groq compile phase."
            ) from exc
        _ensure_os_trust_store()
        kwargs: dict[str, Any] = {"api_key": self._api_key}
        if self._base_url:
            kwargs["base_url"] = self._base_url
        self._client = Groq(**kwargs)
        return self._client

    def _create_completion(self, client: Any, messages: list[dict[str, str]]) -> Any:
        """Call Groq chat completions at temperature 0.

        Requests strict JSON output via ``response_format`` when the installed
        SDK/model supports it, and transparently retries without it otherwise.
        """
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
            # Older SDK signature without a response_format parameter.
            return client.chat.completions.create(**base_kwargs)
        except Exception as exc:  # noqa: BLE001 - only swallowed to retry once
            # Some models/endpoints reject response_format at the API layer;
            # retry once without it. Any other failure propagates unchanged.
            if "response_format" in str(exc).lower():
                return client.chat.completions.create(**base_kwargs)
            raise

    @staticmethod
    def _extract_content(response: Any) -> str:
        """Pull the assistant message text out of a Groq completion, or fail."""
        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError, KeyError, TypeError) as exc:
            raise ContractCompilerError(
                f"Groq response had an unexpected shape: {exc}"
            ) from exc
        if not content or not content.strip():
            raise ContractCompilerError(
                "Groq returned an empty response; no JSON to parse."
            )
        return content

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        """Remove a leading/trailing markdown code fence if the model added one."""
        stripped = text.strip()
        if not stripped.startswith("```"):
            return stripped
        lines = stripped.splitlines()
        # Drop the opening fence line (``` or ```json).
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        # Drop the closing fence line.
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()

    def complete_json(self, messages: list[dict[str, str]]) -> Any:
        """Run one completion and return the parsed JSON payload.

        Raises :class:`ContractCompilerError` when unconfigured, on API
        failure, or when the response is not valid JSON.
        """
        logger.info("Calling Groq: model=%s base_url=%s", self._model, self._base_url or "default")
        client = self._get_client()
        try:
            response = self._create_completion(client, messages)
        except ContractCompilerError:
            logger.exception("Groq call rejected before any network request was made")
            raise
        except Exception as exc:  # noqa: BLE001 - normalise/classify all API failures
            logger.exception("Groq API call failed")
            # Rate limit / quota / token limit / timeout / unavailable / connection
            # errors are retryable — surface them as such so the failover
            # orchestrator moves on to OpenAI. Any other failure is a genuine
            # error that another provider won't fix, so it stays terminal.
            if is_retryable_exception(exc):
                raise RetryableLLMError(
                    f"Groq API call failed: {exc}", provider=self.name
                ) from exc
            raise ContractCompilerError(f"Groq API call failed: {exc}") from exc

        content = self._extract_content(response)
        text = self._strip_code_fences(content)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.exception("Groq response was not valid JSON")
            raise ContractCompilerError(
                f"Groq response was not valid JSON: {exc}"
            ) from exc
        logger.info("Groq call succeeded: model=%s", self._model)
        return payload
