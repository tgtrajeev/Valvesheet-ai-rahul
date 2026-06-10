"""Agent orchestrator — LLM tool_use loop with SSE streaming.

Optimized for minimal token usage:
  1. Prompt caching (cache_control) on system prompt + tool definitions (Anthropic only)
  2. Conversation history pruning (sliding window to cap input tokens)
  3. Tool result truncation (cap large JSON payloads)
  4. Response caching for repeated identical tool calls within a session

Provider is selected via LLM_PROVIDER env var ("anthropic" or "glm").
Messages are always stored in normalized (Anthropic-like) format.
"""

import asyncio
import hashlib
import json
import logging
import uuid
from typing import AsyncGenerator

from ..config import settings
from ..models.schemas import AgentEvent
from .prompts import SYSTEM_PROMPT
from .tools import TOOL_DEFINITIONS, execute_tool
from .llm_provider import (
    LLMProvider,
    LLMRateLimitError,
    LLMAuthenticationError,
    LLMConnectionError,
    LLMAPIError,
    LLMError,
    StreamEventType,
    get_provider,
)

logger = logging.getLogger(__name__)

# Retry config
TOOL_RETRY_DELAYS = [0.5, 1.0, 2.0]       # max 2 retries
API_RETRY_DELAYS = [1.0, 2.0, 4.0]         # max 3 retries for rate limits

# ── Token optimization constants ────────────────────────────────────────────
MAX_HISTORY_TURNS = 20          # Keep last N user+assistant turn pairs
MAX_TOOL_RESULT_CHARS = 4000    # Truncate tool results beyond this
TOOL_RESULT_CACHE: dict[str, dict] = {}   # session-scoped cache for identical tool calls

# Max tools executed concurrently within a single turn — bounds DB/connection
# pressure and shared-cache contention when the model batches many calls.
MAX_PARALLEL_TOOLS = 6


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


def _strip_orphan_tool_blocks(messages: list[dict]) -> list[dict]:
    """Remove tool_use / tool_result blocks whose counterpart is missing in the
    adjacent message. Drops messages that become content-empty.

    The LLM requires every `tool_use` in an assistant message to have a
    matching `tool_result` in the next user message, and vice versa. After
    slicing a conversation for history pruning, a slice boundary can land
    between a tool_use and its matching tool_result — this repairs the result.
    """
    cleaned: list[dict] = []
    for i, msg in enumerate(messages):
        content = msg.get("content")
        if not isinstance(content, list):
            cleaned.append(msg)
            continue

        role = msg.get("role")
        if role == "assistant":
            next_msg = messages[i + 1] if i + 1 < len(messages) else None
            next_result_ids: set[str] = set()
            if next_msg and next_msg.get("role") == "user" and isinstance(next_msg.get("content"), list):
                for b in next_msg["content"]:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        tid = b.get("tool_use_id")
                        if tid:
                            next_result_ids.add(tid)
            new_content = [
                b for b in content
                if not (
                    isinstance(b, dict)
                    and b.get("type") == "tool_use"
                    and b.get("id") not in next_result_ids
                )
            ]
            if new_content:
                cleaned.append({**msg, "content": new_content})
        elif role == "user":
            prev_msg = messages[i - 1] if i > 0 else None
            prev_use_ids: set[str] = set()
            if prev_msg and prev_msg.get("role") == "assistant" and isinstance(prev_msg.get("content"), list):
                for b in prev_msg["content"]:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        tid = b.get("id")
                        if tid:
                            prev_use_ids.add(tid)
            new_content = [
                b for b in content
                if not (
                    isinstance(b, dict)
                    and b.get("type") == "tool_result"
                    and b.get("tool_use_id") not in prev_use_ids
                )
            ]
            if new_content:
                cleaned.append({**msg, "content": new_content})
        else:
            cleaned.append(msg)

    # After drops, the front may now start with assistant — trim until
    # it starts with user.
    while cleaned and cleaned[0].get("role") == "assistant":
        cleaned = cleaned[1:]

    return cleaned


def _prune_history(messages: list[dict]) -> list[dict]:
    """Keep conversation history within bounds to control input tokens.

    Strategy: always keep the first user message (sets context) and the
    last MAX_HISTORY_TURNS messages. This prevents unbounded token growth
    in long conversations while preserving context.
    """
    if len(messages) <= MAX_HISTORY_TURNS + 2:
        return messages

    head = messages[:2]
    tail = messages[-(MAX_HISTORY_TURNS):]

    # Ensure we don't start tail with assistant
    if tail and tail[0].get("role") == "assistant":
        tail = tail[1:]

    combined = list(head) + list(tail)
    return _strip_orphan_tool_blocks(combined)


def _build_system_with_cache(system_text: str) -> list[dict]:
    """Build system prompt with Anthropic prompt caching enabled.

    cache_control: {"type": "ephemeral"} tells Anthropic to cache the
    system prompt across requests. For GLM this is harmless (stripped by converter).
    """
    return [
        {
            "type": "text",
            "text": system_text,
            "cache_control": {"type": "ephemeral"},
        }
    ]


def _build_tools_with_cache(tools: list[dict]) -> list[dict]:
    """Build tool definitions with cache_control on the last tool.

    Anthropic caches everything up to and including the block with
    cache_control. For GLM the converter strips cache_control.
    """
    if not tools:
        return []
    cached = [dict(t) for t in tools]
    cached[-1] = {**cached[-1], "cache_control": {"type": "ephemeral"}}
    return cached


# Pre-build cached versions (they never change at runtime)
_CACHED_SYSTEM = _build_system_with_cache(SYSTEM_PROMPT)
_CACHED_TOOLS = _build_tools_with_cache(TOOL_DEFINITIONS)


async def _retry_tool(tool_name: str, tool_input: dict, project_id: str | None = None) -> dict:
    """Execute a tool with retries on failure."""
    last_error = None
    for attempt in range(1 + len(TOOL_RETRY_DELAYS)):
        try:
            return await execute_tool(tool_name, tool_input, project_id=project_id)
        except Exception as e:
            last_error = e
            if attempt < len(TOOL_RETRY_DELAYS):
                delay = TOOL_RETRY_DELAYS[attempt]
                logger.warning(f"Tool '{tool_name}' failed (attempt {attempt + 1}), retrying in {delay}s: {e}")
                await asyncio.sleep(delay)
            else:
                logger.exception(f"Tool '{tool_name}' failed after {attempt + 1} attempts")
    return {"error": f"Tool '{tool_name}' failed after retries: {str(last_error)[:200]}"}


def _typed_events_for_result(tool_name: str, result: dict) -> list[AgentEvent]:
    """Build the frontend card events (validation / suggestion / datasheet) for a tool result.

    Extracted so it can be reused whether tools run sequentially or in parallel.
    """
    events: list[AgentEvent] = []
    if tool_name == "validate_combination":
        events.append(AgentEvent(type="validation", data=result))
    elif tool_name == "find_valves":
        if result.get("results"):
            events.append(AgentEvent(type="suggestion", data={
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
            }))
    elif tool_name == "generate_datasheet":
        val = result.get("validation") or {}
        errs = [e for e in (val.get("errors") or []) if str(e).strip()]
        if val:
            events.append(AgentEvent(type="validation", data=val))
        if not (result.get("error") or errs):
            events.append(AgentEvent(type="datasheet", data=result))
    elif tool_name == "generate_datasheets_bulk":
        # Fan out one card per datasheet in the batch.
        for ds in (result.get("datasheets") or []):
            if not isinstance(ds, dict):
                continue
            val = ds.get("validation") or {}
            errs = [e for e in (val.get("errors") or []) if str(e).strip()]
            if val:
                events.append(AgentEvent(type="validation", data=val))
            if not (ds.get("error") or errs):
                events.append(AgentEvent(type="datasheet", data=ds))
    return events


def _llm_safe_result(tool_name: str, result: dict) -> dict:
    """Compact a tool result before sending it back to the LLM as context.

    Bulk generation returns up to 60 full datasheets — far too many tokens to feed
    back to the model. The cards already went to the UI; the LLM only needs a summary.
    """
    if tool_name == "generate_datasheets_bulk" and isinstance(result, dict):
        sheets = result.get("datasheets") or []
        return {
            "count": result.get("count", len(sheets)),
            "succeeded": result.get("succeeded"),
            "failed": result.get("failed"),
            "truncated": result.get("truncated", False),
            "vds_codes": [s.get("vds_code") for s in sheets if isinstance(s, dict)],
            "errors": [
                {"vds_code": s.get("vds_code"), "error": s.get("error")}
                for s in sheets if isinstance(s, dict) and s.get("error")
            ],
            "note": "Datasheets were rendered to the user as cards. Summarise the batch; do not re-list every field.",
        }
    return result


def _get_provider() -> LLMProvider:
    """Instantiate the configured LLM provider from active_llm_config()."""
    cfg = settings.active_llm_config()
    return get_provider(
        cfg["provider"],
        api_key=cfg["api_key"],
        base_url=cfg["base_url"],
    )


def _get_model_name() -> str:
    """Return the model name for the active provider."""
    return settings.active_llm_config()["model"]


async def run_agent(
    messages: list[dict],
    session_id: str | None = None,
    prior_agent_messages: list[dict] | None = None,
    project_id: str | None = None,
) -> AsyncGenerator[AgentEvent, None]:
    """Run the agent loop, yielding SSE events.

    Token optimizations applied:
      1. System prompt cached via cache_control (Anthropic only)
      2. Tool definitions cached via cache_control (Anthropic only)
      3. Conversation history pruned to MAX_HISTORY_TURNS
      4. Tool results truncated to MAX_TOOL_RESULT_CHARS
      5. Identical tool calls within a session return cached results
    """
    if not session_id:
        session_id = uuid.uuid4().hex[:16]

    # Per-session tool result cache
    session_tool_cache: dict[str, dict] = {}

    # ── Instantiate provider ──
    try:
        provider = _get_provider()
    except LLMAuthenticationError as e:
        yield AgentEvent(type="error", data={"message": str(e)})
        return
    except Exception as e:
        yield AgentEvent(type="error", data={
            "message": f"Failed to initialize LLM provider: {str(e)[:200]}"
        })
        return

    model = _get_model_name()

    # Build system prompt — inject project context if available
    system_prompt = _CACHED_SYSTEM
    if project_id:
        from .tools import pms_store
        project_pms = pms_store.load_pms(project_id)
        if project_pms:
            class_codes = project_pms.class_codes()
            project_context = (
                f"\n\n========================\n"
                f"ACTIVE PROJECT CONTEXT\n"
                f"========================\n"
                f"Project: {project_pms.metadata.name} (ID: {project_id})\n"
                f"Available piping classes: {', '.join(class_codes)}\n"
                f"Total classes: {len(class_codes)}\n"
                f"When the user asks about PMS data or piping classes, check this project's "
                f"data first using query_pms or query_project_pms. The project_id '{project_id}' "
                f"is automatically applied to all tool calls.\n"
            )
            system_prompt = _build_system_with_cache(SYSTEM_PROMPT + project_context)

    # Build message history: prior session + new messages
    if prior_agent_messages:
        agent_messages = _strip_orphan_tool_blocks(list(prior_agent_messages))
        new_user_msgs = [m for m in messages if m["role"] == "user"]
        if new_user_msgs:
            agent_messages.append({
                "role": "user",
                "content": new_user_msgs[-1]["content"],
            })
    else:
        agent_messages = [
            {"role": msg["role"], "content": msg["content"]}
            for msg in messages
        ]

    # ── Prune history to control input token growth ──
    agent_messages = _prune_history(agent_messages)

    tool_call_count = 0
    max_calls = settings.agent_max_tool_calls
    total_input_tokens = 0
    total_output_tokens = 0
    cache_read_tokens = 0
    cache_creation_tokens = 0

    while True:
        # ── Status: calling LLM ──
        yield AgentEvent(type="status", data={"message": "Calling Valve Agent...", "phase": "llm"})

        # ── Call LLM with streaming + rate limit retry ──
        response = None
        for api_attempt in range(1 + len(API_RETRY_DELAYS)):
            try:
                event_gen, handle = await provider.stream_completion(
                    system=system_prompt,
                    messages=agent_messages,
                    tools=_CACHED_TOOLS,
                    model=model,
                    max_tokens=settings.agent_max_tokens,
                    temperature=settings.agent_temperature,
                )

                # Process the stream
                async for event in event_gen:
                    if event.type == StreamEventType.THINKING:
                        yield AgentEvent(type="thinking", data={"text": event.text})
                    elif event.type == StreamEventType.TEXT:
                        yield AgentEvent(type="text", data={"text": event.text})

                # Get the final response
                response = await provider.get_final_response(handle)

                # Track token usage including cache metrics
                total_input_tokens += response.input_tokens
                total_output_tokens += response.output_tokens
                cache_read_tokens += response.cache_read_tokens
                cache_creation_tokens += response.cache_creation_tokens

                break  # Success — exit retry loop

            except LLMRateLimitError:
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
                        "message": f"{provider.provider_name.upper()} API rate limit reached after retries. Please wait and try again.",
                        "retryable": True,
                    })
                    return

            except LLMAuthenticationError as e:
                yield AgentEvent(type="error", data={
                    "message": str(e) or f"Invalid {provider.provider_name.upper()} API key."
                })
                return

            except LLMConnectionError as e:
                yield AgentEvent(type="error", data={
                    "message": f"Cannot reach {provider.provider_name.upper()} API. Check your internet connection. ({e})",
                    "retryable": True,
                })
                return

            except (LLMAPIError, LLMError, Exception) as e:
                logger.exception(f"{provider.provider_name} API error")
                yield AgentEvent(type="error", data={
                    "message": f"API error: {type(e).__name__}: {str(e)[:200]}",
                    "retryable": True,
                })
                return

        if not response:
            yield AgentEvent(type="error", data={"message": f"Failed to get response from {provider.provider_name.upper()}."})
            return

        # ── Content blocks are already in normalized format ──
        assistant_content = response.content_blocks
        tool_calls = response.tool_calls

        # Append assistant message to history
        agent_messages.append({"role": "assistant", "content": assistant_content})

        # ── If no tool calls, we're done ──
        if not tool_calls:
            break

        # ── Execute tool calls (in parallel, streaming each result as it finishes) ──
        # The model may request several tools in one turn (e.g. generate_datasheet
        # for many VDS codes). Running them concurrently and emitting each card the
        # instant it's ready is far faster than sequential execution and lets the UI
        # show datasheets one-by-one instead of waiting for the whole batch.
        _friendly_tool_msgs = {
            "find_valves": "Analyzing your requirements and finding matching valves...",
            "generate_datasheet": "Generating valve datasheet with AI analysis...",
            "get_piping_class_info": "Retrieving piping class specifications...",
            "validate_combination": "Validating valve combination compatibility...",
            "compare_valves": "Comparing valve specifications side by side...",
            "query_pms": "Looking up PMS material specifications...",
        }

        results_by_id: dict[str, dict] = {}   # tool_use_id -> result dict
        limit_hit = False
        to_run: list = []                      # (tc) tool calls needing live execution

        # First pass: enforce limit, serve cache hits immediately, emit tool_call events.
        for tc in tool_calls:
            tool_call_count += 1
            if tool_call_count > max_calls:
                if not limit_hit:
                    yield AgentEvent(type="error", data={
                        "message": f"Tool call limit ({max_calls}) reached. Stopping."
                    })
                    limit_hit = True
                results_by_id[tc.id] = {"error": "Tool call limit reached, skipped"}
                continue

            yield AgentEvent(type="status", data={
                "message": _friendly_tool_msgs.get(tc.name, "Processing your request..."),
                "phase": "tool",
                "tool": tc.name,
            })
            yield AgentEvent(type="tool_call", data={
                "name": tc.name,
                "input": tc.arguments,
            })

            # Cache hit → resolve now (no API/tool work), still emit its card events.
            ck = _cache_key(tc.name, tc.arguments)
            if ck in session_tool_cache:
                result = session_tool_cache[ck]
                logger.info(f"Tool cache hit: {tc.name} (saved API call)")
                results_by_id[tc.id] = _llm_safe_result(tc.name, result)
                yield AgentEvent(type="tool_result", data={"name": tc.name, "result": result})
                for ev in _typed_events_for_result(tc.name, result):
                    yield ev
            else:
                to_run.append(tc)

        # Launch uncached tools concurrently (capped), stream each result as it completes.
        if to_run:
            _sem = asyncio.Semaphore(MAX_PARALLEL_TOOLS)

            async def _run_capped(_tc):
                # Return the tool call alongside its result — as_completed() yields
                # wrapper awaitables, not the original futures, so we can't map back
                # via a dict. Carrying _tc in the return value is the reliable way.
                async with _sem:
                    _res = await _retry_tool(_tc.name, _tc.arguments, project_id=project_id)
                return _tc, _res

            tasks = [asyncio.ensure_future(_run_capped(tc)) for tc in to_run]
            for fut in asyncio.as_completed(tasks):
                tc, result = await fut
                # Store a compact form for the LLM (bulk returns too much to feed back).
                results_by_id[tc.id] = _llm_safe_result(tc.name, result)
                # Cache successful results (don't cache errors)
                if not result.get("error"):
                    session_tool_cache[_cache_key(tc.name, tc.arguments)] = result

                yield AgentEvent(type="tool_result", data={"name": tc.name, "result": result})
                for ev in _typed_events_for_result(tc.name, result):
                    yield ev

        # Append tool results to history in ORIGINAL call order, truncated for tokens.
        tool_results_content = [
            {
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": _truncate_tool_result(results_by_id.get(tc.id, {"error": "missing result"})),
            }
            for tc in tool_calls
        ]
        agent_messages.append({"role": "user", "content": tool_results_content})

        # If we hit the tool-call limit, stop now
        if limit_hit:
            break

    # ── Emit internal state for session persistence (not sent to client) ──
    yield AgentEvent(type="_agent_state", data={
        "agent_messages": agent_messages,
    })

    # ── Done — include cache metrics for monitoring ──
    yield AgentEvent(type="done", data={
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_creation_tokens": cache_creation_tokens,
    })
