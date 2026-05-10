from __future__ import annotations

from typing import Any

from .config import Settings
from .nvidia_client import NvidiaUnifiedClient
from .utils import extract_json_object


class LLMUnavailable(RuntimeError):
    """Raised when no live language model can be reached."""


class NvidiaChatClient:
    """Thin wrapper around NvidiaUnifiedClient for chat operations."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = NvidiaUnifiedClient(settings)

    @property
    def available(self) -> bool:
        return self._client.available

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.45,
        max_tokens: int = 1800,
    ) -> str:
        if not self.available:
            raise LLMUnavailable("NVIDIA_API_KEY is not configured.")
        return self._client.chat(messages, temperature=temperature, max_tokens=max_tokens)

    def json_chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.35,
        max_tokens: int = 2200,
    ) -> dict[str, Any]:
        content = self.chat(messages, temperature=temperature, max_tokens=max_tokens)
        return extract_json_object(content)
