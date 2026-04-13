"""Agent orchestrator — Claude tool_use loop with SSE streaming.

Optimized for minimal token usage:
  1. Prompt caching (cache_control) on system prompt + tool definitions
  2. Conversation history pruning (sliding window to cap input tokens)
  3. Tool result truncation (cap large JSON payloads)
  4. Response caching for repeated identical tool calls within a session
"""

import asyncio
import hashlib
import json
import logging
import uuid
from typing import AsyncGenerator

import anthropic

from ..config import settings
from ..models.schemas import AgentEvent
from .prompts import SYSTEM_PROMPT
from .tools import TOOL_DEFINITIONS, execute_tool

logger = logging.getLogger(__name__)

# Retry config
TOOL_RETRY_DELAYS = [0.5, 1.0, 2.0]       # max 2 retries
API_RETRY_DELAYS = [1.0, 2.0, 4.0]         # max 3 retries for rate limits

# ── Token optimization constants ────────────────────────────────────────────
MAX_HISTORY_TURNS = 20          # Keep last N user+assistant turn pairs
MAX_TOOL_RESULT_CHARS = 4000    # Truncate tool results beyond this
TOOL_RESULT_CACHE: dict[str, dict] = {}   # session-scoped cache for identical tool calls


def _cache_key(tool_name: str, tool_input: dict) -> str:
    """Deterministic cache key for a tool call."""
    raw = f"{tool_name}:{json.dumps(tool_input, sort_keys=True)}"
    return hashlib.md5(raw.encode()).hexdigest()


def _truncate_tool_result(result: dict) -> str:
    """Serialize tool result, truncating if too large to save tokens."""
    raw = json.dumps(result)
    if len(raw) <= MAX_TOOL_RESULT_CHARS:
        return raw
    # For large results, keep structure but trim long arrays
    trimmed = _trim_large_fields(result)
    raw = json.dumps(trimmed)
    if len(raw) <= MAX_TOOL_RESULT_CHARS:
        return raw
    # Hard truncate as last resort
    return raw[:MAX_TOOL_RESULT_CHARS - 50] + '..."truncated for brevity"}'


def _trim_large_fields(obj, depth=0):
    """Recursively trim large lists/strings in tool results."""
    if depth > 3:
        return obj
    if isinstance(obj, dict):
        return {k: _trim_large_fields(v, depth + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        if len(obj) > 8:
            return obj[:8] + [f"... and {len(obj) - 8} more items"]
        return [_trim_large_fields(v, depth + 1) for v in obj]
    if isinstance(obj, str) and len(obj) > 500:
        return obj[:500] + "..."
    return obj


def _prune_history(messages: list[dict]) -> list[dict]:
    """Keep conversation history within bounds to control input tokens.

    Strategy: always keep the first user message (sets context) and the
    last MAX_HISTORY_TURNS messages. This prevents unbounded token growth
    in long conversations while preserving context.
    """
    if len(messages) <= MAX_HISTORY_TURNS + 2:
        return messages

    # Keep first 2 messages (first user msg + first assistant response)
    # plus the last MAX_HISTORY_TURNS messages
    head = messages[:2]
    tail = messages[-(MAX_HISTORY_TURNS):]

    # Ensure we don't start tail with assistant (Anthropic requires user-first)
    if tail and tail[0].get("role") == "assistant":
        tail = tail[1:]

    return head + tail


def _build_system_with_cache() -> list[dict]:
    """Build system prompt with Anthropic prompt caching enabled.

    cache_control: {"type": "ephemeral"} tells Anthropic to cache the
    system prompt across requests. Since it's identical every time,
    subsequent calls read from cache at ~90% token cost reduction.
    """
    return [
        {
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }
    ]


def _build_tools_with_cache() -> list[dict]:
    """Build tool definitions with cache_control on the last tool.

    Anthropic caches everything up to and including the block with
    cache_control. Placing it on the last tool definition caches all tools.
    """
    if not TOOL_DEFINITIONS:
        return []
    tools = [dict(t) for t in TOOL_DEFINITIONS]
    # Add cache_control to the last tool definition
    tools[-1] = {**tools[-1], "cache_control": {"type": "ephemeral"}}
    return tools


# Pre-build cached versions (they never change at runtime)
_CACHED_SYSTEM = _build_system_with_cache()
_CACHED_TOOLS = _build_tools_with_cache()


async def _retry_tool(tool_name: str, tool_input: dict) -> dict:
    """Execute a tool with retries on failure."""
    last_error = None
    for attempt in range(1 + len(TOOL_RETRY_DELAYS)):
        try:
            return await execute_tool(tool_name, tool_input)
        except Exception as e:
            last_error = e
            if attempt < len(TOOL_RETRY_DELAYS):
                delay = TOOL_RETRY_DELAYS[attempt]
                logger.warning(f"Tool '{tool_name}' failed (attempt {attempt + 1}), retrying in {delay}s: {e}")
                await asyncio.sleep(delay)
            else:
                logger.exception(f"Tool '{tool_name}' failed after {attempt + 1} attempts")
    return {"error": f"Tool '{tool_name}' failed after retries: {str(last_error)[:200]}"}


async def run_agent(
    messages: list[dict],
    session_id: str | None = None,
    prior_agent_messages: list[dict] | None = None,
) -> AsyncGenerator[AgentEvent, None]:
    """Run the agent loop, yielding SSE events.

    Token optimizations applied:
      1. System prompt cached via cache_control (saves ~580 tokens/call after first)
      2. Tool definitions cached via cache_control (saves ~2K tokens/call after first)
      3. Conversation history pruned to MAX_HISTORY_TURNS
      4. Tool results truncated to MAX_TOOL_RESULT_CHARS
      5. Identical tool calls within a session return cached results (0 extra tokens)
    """
    if not session_id:
        session_id = uuid.uuid4().hex[:16]

    # Per-session tool result cache (cleared each session)
    session_tool_cache: dict[str, dict] = {}

    # Validate API key before doing anything
    if not settings.anthropic_api_key or settings.anthropic_api_key.startswith("your-"):
        yield AgentEvent(type="error", data={
            "message": "Anthropic API key not configured. Set ANTHROPIC_API_KEY in your .env file."
        })
        return

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    # Build message history: prior session + new messages
    if prior_agent_messages:
        anthropic_messages = list(prior_agent_messages)
        # Append only new user messages (the last user message from request)
        new_user_msgs = [m for m in messages if m["role"] == "user"]
        if new_user_msgs:
            anthropic_messages.append({
                "role": "user",
                "content": new_user_msgs[-1]["content"],
            })
    else:
        anthropic_messages = [
            {"role": msg["role"], "content": msg["content"]}
            for msg in messages
        ]

    # ── Prune history to control input token growth ──
    anthropic_messages = _prune_history(anthropic_messages)

    tool_call_count = 0
    max_calls = settings.agent_max_tool_calls
    total_input_tokens = 0
    total_output_tokens = 0
    cache_read_tokens = 0
    cache_creation_tokens = 0

    while True:
        # ── Status: calling LLM ──
        yield AgentEvent(type="status", data={"message": "Calling Valve Agent...", "phase": "llm"})

        # ── Call Claude with streaming + prompt caching + rate limit retry ──
        final = None
        for api_attempt in range(1 + len(API_RETRY_DELAYS)):
            try:
                stream = client.messages.stream(
                    model=settings.agent_model,
                    max_tokens=settings.agent_max_tokens,
                    temperature=settings.agent_temperature,
                    system=_CACHED_SYSTEM,
                    messages=anthropic_messages,
                    tools=_CACHED_TOOLS,
                )

                # Process the stream
                assistant_content = []
                tool_uses = []
                accumulated_text = ""

                async with stream as s:
                    async for event in s:
                        if event.type == "content_block_start":
                            block = event.content_block
                            if block.type == "thinking":
                                yield AgentEvent(type="thinking", data={"text": ""})

                        elif event.type == "content_block_delta":
                            delta = event.delta
                            if hasattr(delta, "thinking") and delta.thinking:
                                yield AgentEvent(type="thinking", data={"text": delta.thinking})
                            elif hasattr(delta, "text") and delta.text:
                                accumulated_text += delta.text
                                yield AgentEvent(type="text", data={"text": delta.text})

                    # Get the final message
                    final = await s.get_final_message()

                # Track token usage including cache metrics
                if final and final.usage:
                    total_input_tokens += final.usage.input_tokens
                    total_output_tokens += final.usage.output_tokens
                    # Track cache performance
                    if hasattr(final.usage, "cache_read_input_tokens"):
                        cache_read_tokens += final.usage.cache_read_input_tokens or 0
                    if hasattr(final.usage, "cache_creation_input_tokens"):
                        cache_creation_tokens += final.usage.cache_creation_input_tokens or 0

                break  # Success — exit retry loop

            except anthropic.RateLimitError:
                if api_attempt < len(API_RETRY_DELAYS):
                    delay = API_RETRY_DELAYS[api_attempt]
                    logger.warning(f"Rate limited (attempt {api_attempt + 1}), retrying in {delay}s")
                    yield AgentEvent(type="status", data={
                        "message": f"Rate limited — retrying in {int(delay)}s...",
                        "phase": "retry",
                    })
                    await asyncio.sleep(delay)
                else:
                    yield AgentEvent(type="error", data={
                        "message": "Anthropic API rate limit reached after retries. Please wait and try again.",
                        "retryable": True,
                    })
                    return

            except anthropic.AuthenticationError:
                yield AgentEvent(type="error", data={
                    "message": "Invalid Anthropic API key. Please check ANTHROPIC_API_KEY in your .env file."
                })
                return

            except anthropic.APIConnectionError as e:
                yield AgentEvent(type="error", data={
                    "message": f"Cannot reach Anthropic API. Check your internet connection. ({e})",
                    "retryable": True,
                })
                return

            except Exception as e:
                logger.exception("Anthropic API error")
                yield AgentEvent(type="error", data={
                    "message": f"API error: {type(e).__name__}: {str(e)[:200]}",
                    "retryable": True,
                })
                return

        if not final:
            yield AgentEvent(type="error", data={"message": "Failed to get response from Claude."})
            return

        # ── Collect content blocks ──
        assistant_content = []
        tool_uses = []
        for block in final.content:
            if block.type == "text":
                assistant_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                assistant_content.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
                tool_uses.append(block)
            elif block.type == "thinking":
                assistant_content.append({"type": "thinking", "thinking": block.thinking})

        # Append assistant message to history
        anthropic_messages.append({"role": "assistant", "content": assistant_content})

        # ── If no tool calls, we're done ──
        if final.stop_reason != "tool_use" or not tool_uses:
            break

        # ── Execute tool calls ──
        tool_results_content = []

        for tool_block in tool_uses:
            tool_call_count += 1

            if tool_call_count > max_calls:
                yield AgentEvent(type="error", data={
                    "message": f"Tool call limit ({max_calls}) reached. Stopping."
                })
                tool_results_content.append({
                    "type": "tool_result",
                    "tool_use_id": tool_block.id,
                    "content": json.dumps({"error": "Tool call limit reached"}),
                })
                break

            # Emit status + tool_call events
            _friendly_tool_msgs = {
                "find_valves": "Analyzing your requirements and finding matching valves...",
                "generate_datasheet": "Generating valve datasheet with AI analysis...",
                "get_piping_class_info": "Retrieving piping class specifications...",
                "validate_combination": "Validating valve combination compatibility...",
                "compare_valves": "Comparing valve specifications side by side...",
                "query_pms": "Looking up PMS material specifications...",
            }
            yield AgentEvent(type="status", data={
                "message": _friendly_tool_msgs.get(tool_block.name, f"Processing your request..."),
                "phase": "tool",
                "tool": tool_block.name,
            })
            yield AgentEvent(type="tool_call", data={
                "name": tool_block.name,
                "input": tool_block.input,
            })

            # ── Check session tool cache first (avoids re-execution + re-sending) ──
            ck = _cache_key(tool_block.name, tool_block.input)
            if ck in session_tool_cache:
                result = session_tool_cache[ck]
                logger.info(f"Tool cache hit: {tool_block.name} (saved API call)")
            else:
                result = await _retry_tool(tool_block.name, tool_block.input)
                # Cache successful results (don't cache errors)
                if not result.get("error"):
                    session_tool_cache[ck] = result

            # Emit tool_result event (full result to frontend)
            yield AgentEvent(type="tool_result", data={
                "name": tool_block.name,
                "result": result,
            })

            # Emit typed events for frontend card rendering
            if tool_block.name == "validate_combination":
                yield AgentEvent(type="validation", data=result)
            elif tool_block.name == "find_valves":
                if result.get("results"):
                    yield AgentEvent(type="suggestion", data={
                        "suggestions": [
                            {
                                "type": "combination",
                                "title": r["vds_code"],
                                "description": (
                                    f"{r['valve_type']} | {r['piping_class']} | "
                                    f"{r.get('body_material', '')[:40]}"
                                ),
                                "action": {"vds_code": r["vds_code"]},
                                "meta": {
                                    "valve_type": r.get("valve_type", ""),
                                    "piping_class": r.get("piping_class", ""),
                                    "pressure_class": r.get("pressure_class", ""),
                                    "size_range": r.get("size_range", ""),
                                    "body_material": r.get("body_material", "")[:60],
                                    "end_connections": r.get("end_connections", ""),
                                    "sour_service": r.get("sour_service", ""),
                                },
                            }
                            for r in result["results"][:12]
                        ]
                    })
            elif tool_block.name == "generate_datasheet":
                if result.get("error") and result.get("validation"):
                    yield AgentEvent(type="validation", data=result["validation"])
                elif not result.get("error"):
                    yield AgentEvent(type="datasheet", data=result)

            # ── Truncate tool result before appending to messages (saves tokens) ──
            result_str = _truncate_tool_result(result)

            tool_results_content.append({
                "type": "tool_result",
                "tool_use_id": tool_block.id,
                "content": result_str,
            })

        # Append tool results to message history for next loop iteration
        anthropic_messages.append({"role": "user", "content": tool_results_content})

    # ── Emit internal state for session persistence (not sent to client) ──
    yield AgentEvent(type="_agent_state", data={
        "agent_messages": anthropic_messages,
    })

    # ── Done — include cache metrics for monitoring ──
    yield AgentEvent(type="done", data={
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_creation_tokens": cache_creation_tokens,
    })
