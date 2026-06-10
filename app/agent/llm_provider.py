"""LLM Provider abstraction layer.

Defines a unified interface for LLM completions so the orchestrator
doesn't care whether it's talking to Anthropic, GLM (Zhipu), or any
OpenAI-compatible endpoint.

Messages are stored in *normalized* (Anthropic-like) format:
  - assistant tool calls   = content blocks with type "tool_use"
  - user tool results      = content blocks with type "tool_result"
  - thinking blocks        = content blocks with type "thinking"

Each provider converts to/from its native wire format at the API boundary.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncGenerator


# ── Neutral data classes ────────────────────────────────────────────────────

class StreamEventType(str, Enum):
    TEXT = "text"
    THINKING = "thinking"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_DELTA = "tool_call_delta"
    DONE = "done"
    ERROR = "error"


@dataclass
class LLMToolCall:
    """A single tool invocation from the LLM."""
    id: str
    name: str
    arguments: dict  # always parsed dict, never raw JSON string


@dataclass
class LLMStreamEvent:
    """A single event from a streaming completion."""
    type: StreamEventType
    text: str = ""
    tool_call: LLMToolCall | None = None
    # For TOOL_CALL_DELTA: partial arguments JSON chunk
    arguments_delta: str = ""


@dataclass
class LLMResponse:
    """Final (non-streaming) response after stream is consumed."""
    content_blocks: list[dict]      # normalized content blocks (text/tool_use/thinking)
    tool_calls: list[LLMToolCall]   # extracted tool calls for easy iteration
    stop_reason: str = ""           # "end_turn", "tool_use", "max_tokens", etc.
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


# ── Exceptions ──────────────────────────────────────────────────────────────

class LLMError(Exception):
    """Base exception for LLM provider errors."""
    retryable: bool = False


class LLMRateLimitError(LLMError):
    """Rate limit / quota exceeded."""
    retryable = True


class LLMAuthenticationError(LLMError):
    """Invalid API key or unauthorized."""
    retryable = False


class LLMConnectionError(LLMError):
    """Cannot reach the LLM API."""
    retryable = True


class LLMAPIError(LLMError):
    """Generic API error (malformed request, server error, etc.)."""
    retryable = True


# ── Abstract provider ───────────────────────────────────────────────────────

class LLMProvider(ABC):
    """Abstract base for LLM providers.

    Subclasses implement:
      - stream_completion()   for the streaming tool-use loop
      - provider_name         for logging / telemetry
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Short identifier: 'anthropic', 'glm', etc."""

    @abstractmethod
    async def stream_completion(
        self,
        *,
        system: str | list[dict],
        messages: list[dict],
        tools: list[dict],
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.1,
    ) -> tuple[AsyncGenerator[LLMStreamEvent, None], Any]:
        """Start a streaming completion.

        Args:
            system:      System prompt (str or Anthropic-style list of text blocks)
            messages:    Conversation in *normalized* (Anthropic-like) format
            tools:       Tool definitions in *Anthropic* format (canonical)
            model:       Model name/ID
            max_tokens:  Max output tokens
            temperature: Sampling temperature

        Returns:
            (event_generator, handle)
            - event_generator yields LLMStreamEvent
            - handle is an opaque object the caller passes to get_final_response()

        Raises:
            LLMRateLimitError, LLMAuthenticationError, LLMConnectionError, LLMAPIError
        """

    @abstractmethod
    async def get_final_response(self, handle: Any) -> LLMResponse:
        """Extract the final LLMResponse after the stream is consumed.

        The *handle* is the second value returned by stream_completion().
        """


# ── Factory ─────────────────────────────────────────────────────────────────

# Providers that speak the OpenAI wire format (routed through one client).
_OPENAI_COMPATIBLE = {
    "gemini", "google", "openai", "qwen", "dashscope", "deepseek", "glm", "zhipu",
    "openrouter",
}


def get_provider(
    provider_name: str,
    *,
    api_key: str = "",
    base_url: str = "",
    **kwargs,
) -> LLMProvider:
    """Instantiate a provider by name.

    Args:
        provider_name: anthropic | gemini | openai | qwen | deepseek | glm
        api_key:       Provider API key
        base_url:      Custom base URL (used by all OpenAI-compatible providers)

    Returns:
        An LLMProvider instance ready to use.
    """
    name = provider_name.strip().lower()

    if name == "anthropic":
        from .providers.anthropic_provider import AnthropicProvider
        return AnthropicProvider(api_key=api_key, **kwargs)

    if name in _OPENAI_COMPATIBLE:
        from .providers.glm_provider import OpenAICompatibleProvider
        return OpenAICompatibleProvider(
            api_key=api_key,
            base_url=base_url,
            provider_label=name,
            **kwargs,
        )

    raise ValueError(
        f"Unknown LLM provider '{provider_name}'. "
        f"Supported: anthropic, gemini, openai, qwen, deepseek, glm"
    )
