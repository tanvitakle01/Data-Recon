"""Provider interface + shared JSON-response helpers for LLM clients.

Every LLM provider exposes the exact same surface the codebase already relied
on for Groq — ``complete_json(messages) -> parsed JSON`` plus ``name`` and
``is_configured`` — so the failover orchestrator and both call sites (the
contract compiler and the script generator) are provider-agnostic.
"""

from __future__ import annotations

import json
from typing import Any, Protocol, runtime_checkable

from backend.recon_engine.compiler.base import ContractCompilerError


@runtime_checkable
class LLMProvider(Protocol):
    """Minimal provider contract: messages in, parsed-JSON object out."""

    #: short provenance tag (e.g. "groq", "openai").
    name: str

    @property
    def is_configured(self) -> bool:  # pragma: no cover - structural
        ...

    def complete_json(self, messages: list[dict[str, str]]) -> Any:  # pragma: no cover - structural
        ...


def strip_code_fences(text: str) -> str:
    """Remove a leading/trailing markdown code fence if the model added one."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def extract_message_content(response: Any, *, provider: str) -> str:
    """Pull the assistant message text out of a chat completion, or fail."""
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, KeyError, TypeError) as exc:
        raise ContractCompilerError(
            f"{provider} response had an unexpected shape: {exc}"
        ) from exc
    if not content or not content.strip():
        raise ContractCompilerError(
            f"{provider} returned an empty response; no JSON to parse."
        )
    return content


def parse_json_payload(text: str, *, provider: str) -> Any:
    """Parse model output as JSON, stripping code fences first."""
    cleaned = strip_code_fences(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ContractCompilerError(
            f"{provider} response was not valid JSON: {exc}"
        ) from exc
