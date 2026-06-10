"""Anthropic provider — wraps the existing anthropic.AsyncAnthropic streaming code.

This is a thin adapter: messages are already in normalized (Anthropic) format,
so no conversion is needed.  Tool definitions are in Anthropic format natively.
The only job is to map Anthropic SDK objects to the neutral LLMStreamEvent /
LLMResponse dataclasses.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncGenerator

import anthropic

from ..llm_provider import (
    LLMAPIError,
    LLMAuthenticationError,
    LLMConnectionError,
    LLMProvider,
    LLMRateLimitError,
    LLMResponse,
    LLMStreamEvent,
    LLMToolCall,
    StreamEventType,
)

logger = logging.getLogger(__name__)


class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider using the native SDK."""

    def __init__(self, *, api_key: str = "", **kwargs):
        if not api_key or api_key.startswith("your-"):
            raise LLMAuthenticationError(
                "Anthropic API key not configured. Set ANTHROPIC_API_KEY in your .env file."
            )
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    @property
    def provider_name(self) -> str:
        return "anthropic"

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
        """Start streaming completion from Anthropic.

        Messages and tools are already in Anthropic format — pass through directly.
        """
        # Build the stream handle (lazy — actual HTTP call happens in __aenter__)
        try:
            stream_mgr = self._client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=messages,
                tools=tools,
            )
        except anthropic.AuthenticationError as e:
            raise LLMAuthenticationError(str(e)) from e
        except anthropic.RateLimitError as e:
            raise LLMRateLimitError(str(e)) from e
        except anthropic.APIConnectionError as e:
            raise LLMConnectionError(str(e)) from e
        except Exception as e:
            raise LLMAPIError(str(e)) from e

        # We store the stream manager so get_final_response can access it
        # The actual generator does the __aenter__ to start HTTP streaming
        handle = {"stream_mgr": stream_mgr, "stream_obj": None, "final": None}

        async def _event_gen() -> AsyncGenerator[LLMStreamEvent, None]:
            try:
                async with stream_mgr as s:
                    handle["stream_obj"] = s
                    async for event in s:
                        if event.type == "content_block_start":
                            block = event.content_block
                            if block.type == "thinking":
                                yield LLMStreamEvent(
                                    type=StreamEventType.THINKING,
                                    text="",
                                )

                        elif event.type == "content_block_delta":
                            delta = event.delta
                            if hasattr(delta, "thinking") and delta.thinking:
                                yield LLMStreamEvent(
                                    type=StreamEventType.THINKING,
                                    text=delta.thinking,
                                )
                            elif hasattr(delta, "text") and delta.text:
                                yield LLMStreamEvent(
                                    type=StreamEventType.TEXT,
                                    text=delta.text,
                                )

                    # Get the final message after stream completes
                    handle["final"] = await s.get_final_message()

            except anthropic.RateLimitError as e:
                raise LLMRateLimitError(str(e)) from e
            except anthropic.AuthenticationError as e:
                raise LLMAuthenticationError(str(e)) from e
            except anthropic.APIConnectionError as e:
                raise LLMConnectionError(str(e)) from e
            except Exception as e:
                if not isinstance(e, (LLMRateLimitError, LLMAuthenticationError, LLMConnectionError)):
                    raise LLMAPIError(str(e)) from e
                raise

        return _event_gen(), handle

    async def get_final_response(self, handle: Any) -> LLMResponse:
        """Extract the final response after stream is consumed."""
        final = handle.get("final")
        if not final:
            return LLMResponse(content_blocks=[], tool_calls=[], stop_reason="error")

        # Convert Anthropic content blocks to normalized format
        content_blocks: list[dict] = []
        tool_calls: list[LLMToolCall] = []

        for block in final.content:
            if block.type == "text":
                content_blocks.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                content_blocks.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
                tool_calls.append(LLMToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=block.input,
                ))
            elif block.type == "thinking":
                content_blocks.append({"type": "thinking", "thinking": block.thinking})

        # Token usage
        input_tokens = final.usage.input_tokens if final.usage else 0
        output_tokens = final.usage.output_tokens if final.usage else 0
        cache_read = 0
        cache_creation = 0
        if final.usage:
            if hasattr(final.usage, "cache_read_input_tokens"):
                cache_read = final.usage.cache_read_input_tokens or 0
            if hasattr(final.usage, "cache_creation_input_tokens"):
                cache_creation = final.usage.cache_creation_input_tokens or 0

        return LLMResponse(
            content_blocks=content_blocks,
            tool_calls=tool_calls,
            stop_reason=final.stop_reason or "",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read,
            cache_creation_tokens=cache_creation,
        )
