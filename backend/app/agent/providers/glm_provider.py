"""OpenAI-compatible provider — drives any OpenAI-style /chat/completions API.

Used for every non-Anthropic provider: Gemini, OpenAI, Qwen, DeepSeek, GLM.
They all speak the OpenAI wire format, so a single `openai.AsyncOpenAI` client
pointed at the right base_url handles all of them — only base_url / key / model
differ (resolved in config.active_llm_config()).

Key differences from Anthropic handled here:

1. System prompt  -> {"role": "system"} message (not a separate param)
2. Tool defs      -> OpenAI function format (input_schema -> parameters)
3. Tool calls     -> streamed incrementally (name in first chunk, arguments accumulate)
4. Tool results   -> role "tool" messages (not tool_result blocks in user messages)
5. Arguments      -> JSON string (needs json.loads)
6. Thinking       -> not supported (stripped)
7. Cache control  -> not supported (no-op)
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncGenerator

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
from ..message_converter import normalized_to_openai, openai_response_to_normalized
from ..tool_converter import anthropic_to_openai_tools

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider(LLMProvider):
    """Generic provider for any OpenAI-compatible API (Gemini, OpenAI, Qwen, DeepSeek, GLM)."""

    def __init__(
        self,
        *,
        api_key: str = "",
        base_url: str = "",
        provider_label: str = "openai",
        **kwargs,
    ):
        self._label = provider_label or "openai"
        if not api_key:
            raise LLMAuthenticationError(
                f"{self._label.upper()} API key not configured. "
                f"Set {self._label.upper()}_API_KEY in your .env file."
            )
        try:
            import openai
        except ImportError:
            raise LLMAPIError(
                "openai package not installed. Run: pip install openai>=1.30.0"
            )

        self._client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=base_url or None,   # None -> OpenAI SDK uses its own default (api.openai.com)
            max_retries=0,    # We handle retries in the orchestrator — don't let SDK retry with 60s waits
            timeout=90.0,     # Fail fast: SDK default is 600s (10 min); cap each request at 90s so a stalled stream can't hang the agent
        )

    @property
    def provider_name(self) -> str:
        return self._label

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
        """Start streaming completion from GLM via OpenAI SDK.

        Converts normalized messages + Anthropic tools to OpenAI format,
        then streams and converts events back to neutral format.
        """
        import openai

        # Convert messages from normalized to OpenAI format
        openai_messages = normalized_to_openai(messages, system=system)

        # Convert tool definitions from Anthropic to OpenAI format
        openai_tools = anthropic_to_openai_tools(tools)

        # Handle for collecting final response data
        handle: dict[str, Any] = {
            "content": "",
            "tool_calls_raw": [],
            "input_tokens": 0,
            "output_tokens": 0,
            "finished": False,
        }

        async def _event_gen() -> AsyncGenerator[LLMStreamEvent, None]:
            try:
                # Build API kwargs
                api_kwargs: dict[str, Any] = {
                    "model": model,
                    "messages": openai_messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "stream": True,
                    "stream_options": {"include_usage": True},
                }
                # Only include tools if we have any
                if openai_tools:
                    api_kwargs["tools"] = openai_tools

                stream = await self._client.chat.completions.create(**api_kwargs)

                # Accumulate tool calls by index (they arrive incrementally)
                # Format: {index: {"id": str, "name": str, "arguments": str}}
                tc_accum: dict[int, dict] = {}

                async for chunk in stream:
                    # Extract usage from the final chunk
                    if chunk.usage:
                        handle["input_tokens"] = chunk.usage.prompt_tokens or 0
                        handle["output_tokens"] = chunk.usage.completion_tokens or 0

                    if not chunk.choices:
                        continue

                    choice = chunk.choices[0]
                    delta = choice.delta

                    if delta is None:
                        continue

                    # Text content
                    if delta.content:
                        handle["content"] += delta.content
                        yield LLMStreamEvent(
                            type=StreamEventType.TEXT,
                            text=delta.content,
                        )

                    # Tool calls (streamed incrementally)
                    if delta.tool_calls:
                        for tc_delta in delta.tool_calls:
                            idx = tc_delta.index

                            if idx not in tc_accum:
                                tc_accum[idx] = {
                                    "id": "",
                                    "name": "",
                                    "arguments": "",
                                }

                            if tc_delta.id:
                                tc_accum[idx]["id"] = tc_delta.id

                            if tc_delta.function:
                                if tc_delta.function.name:
                                    tc_accum[idx]["name"] = tc_delta.function.name
                                    # Emit tool_call_start when we get the name
                                    yield LLMStreamEvent(
                                        type=StreamEventType.TOOL_CALL_START,
                                        tool_call=LLMToolCall(
                                            id=tc_accum[idx]["id"],
                                            name=tc_delta.function.name,
                                            arguments={},
                                        ),
                                    )

                                if tc_delta.function.arguments:
                                    tc_accum[idx]["arguments"] += tc_delta.function.arguments

                # Store accumulated tool calls in handle
                handle["tool_calls_raw"] = [
                    tc_accum[i] for i in sorted(tc_accum.keys())
                ]
                handle["finished"] = True

            except openai.AuthenticationError as e:
                raise LLMAuthenticationError(str(e)) from e
            except openai.RateLimitError as e:
                raise LLMRateLimitError(str(e)) from e
            except openai.APIConnectionError as e:
                raise LLMConnectionError(str(e)) from e
            except Exception as e:
                if not isinstance(e, (LLMRateLimitError, LLMAuthenticationError, LLMConnectionError)):
                    raise LLMAPIError(str(e)) from e
                raise

        return _event_gen(), handle

    async def get_final_response(self, handle: Any) -> LLMResponse:
        """Build the final LLMResponse from accumulated stream data."""
        content_text = handle.get("content", "")
        raw_tool_calls = handle.get("tool_calls_raw", [])

        # Parse tool calls: arguments are JSON strings, convert to dicts
        tool_calls: list[LLMToolCall] = []
        openai_tool_calls: list[dict] = []

        for tc in raw_tool_calls:
            args_str = tc.get("arguments", "{}")
            try:
                args = json.loads(args_str)
            except (json.JSONDecodeError, TypeError):
                logger.warning(f"Failed to parse tool arguments for {tc.get('name')}: {args_str[:200]}")
                args = {"_raw_arguments": args_str}

            tool_calls.append(LLMToolCall(
                id=tc.get("id", ""),
                name=tc.get("name", ""),
                arguments=args,
            ))
            # Build OpenAI-format tool call for the converter
            openai_tool_calls.append({
                "id": tc.get("id", ""),
                "type": "function",
                "function": {
                    "name": tc.get("name", ""),
                    "arguments": args_str,
                },
            })

        # Convert to normalized content blocks
        content_blocks = openai_response_to_normalized(
            content=content_text or None,
            tool_calls=openai_tool_calls if openai_tool_calls else None,
        )

        # Determine stop reason
        stop_reason = "end_turn"
        if tool_calls:
            stop_reason = "tool_use"

        return LLMResponse(
            content_blocks=content_blocks,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            input_tokens=handle.get("input_tokens", 0),
            output_tokens=handle.get("output_tokens", 0),
            cache_read_tokens=0,       # OpenAI-compatible providers: no Anthropic-style caching
            cache_creation_tokens=0,
        )


# Backward-compatible alias — earlier code/imports referenced GLMProvider.
GLMProvider = OpenAICompatibleProvider
