"""Agent orchestrator — Claude tool_use loop with SSE streaming.

This is the core agent loop. It:
1. Sends messages + tools to Claude
2. Streams back text, thinking, tool_calls
3. Executes tools when Claude requests them
4. Loops until Claude finishes (stop_reason="end_turn") or max tool calls reached
5. Supports conversation resumption via prior_agent_messages
6. Retries failed tool calls and rate-limited API calls with exponential backoff
"""

import asyncio
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


async def run_agent(
    messages: list[dict],
    session_id: str | None = None,
    prior_agent_messages: list[dict] | None = None,
    project_id: str | None = None,
) -> AsyncGenerator[AgentEvent, None]:
    """Run the agent loop, yielding SSE events.

    Args:
        messages: Current user messages (from this request).
        session_id: Session ID for tracking.
        prior_agent_messages: Full Anthropic message history from a previous session
                              for conversation resumption.
        project_id: Optional project ID for project-scoped PMS resolution.
    """
    if not session_id:
        session_id = uuid.uuid4().hex[:16]

    # Validate API key before doing anything
    if not settings.anthropic_api_key or settings.anthropic_api_key.startswith("your-"):
        yield AgentEvent(type="error", data={
            "message": "Anthropic API key not configured. Set ANTHROPIC_API_KEY in your .env file."
        })
        return

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    # Build system prompt — inject project context if available
    system_prompt = SYSTEM_PROMPT
    if project_id:
        from ..pms import store as pms_store
        project_pms = pms_store.load_pms(project_id)
        if project_pms:
            class_codes = project_pms.class_codes()
            system_prompt = (
                SYSTEM_PROMPT
                + f"\n\n========================\n"
                f"ACTIVE PROJECT CONTEXT\n"
                f"========================\n"
                f"Project: {project_pms.metadata.name} (ID: {project_id})\n"
                f"Available piping classes: {', '.join(class_codes)}\n"
                f"Total classes: {len(class_codes)}\n"
                f"When the user asks about PMS data or piping classes, check this project's "
                f"data first using query_pms or query_project_pms. The project_id '{project_id}' "
                f"is automatically applied to all tool calls.\n"
            )

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

    tool_call_count = 0
    max_calls = settings.agent_max_tool_calls
    total_input_tokens = 0
    total_output_tokens = 0

    while True:
        # ── Status: calling LLM ──
        yield AgentEvent(type="status", data={"message": "Calling Valve Agent...", "phase": "llm"})

        # ── Call Claude with streaming + rate limit retry ──
        final = None
        for api_attempt in range(1 + len(API_RETRY_DELAYS)):
            try:
                stream = client.messages.stream(
                    model=settings.agent_model,
                    max_tokens=settings.agent_max_tokens,
                    temperature=settings.agent_temperature,
                    system=system_prompt,
                    messages=anthropic_messages,
                    tools=TOOL_DEFINITIONS,
                )

                # Process the stream — the actual HTTP request happens here in __aenter__
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

                # Track token usage
                if final and final.usage:
                    total_input_tokens += final.usage.input_tokens
                    total_output_tokens += final.usage.output_tokens

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

            # Execute with retry
            result = await _retry_tool(tool_block.name, tool_block.input, project_id=project_id)
            result_str = json.dumps(result)

            # Emit tool_result event
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
                    # Emit validation event first (so frontend can attach errors/warnings)
                    if result.get("validation"):
                        yield AgentEvent(type="validation", data=result["validation"])
                    yield AgentEvent(type="datasheet", data=result)

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

    # ── Done ──
    yield AgentEvent(type="done", data={
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
    })
