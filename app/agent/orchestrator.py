"""Agent orchestrator — Claude tool_use loop with SSE streaming.

This is the core agent loop. It:
1. Sends messages + tools to Claude
2. Streams back text, thinking, tool_calls
3. Executes tools when Claude requests them
4. Loops until Claude finishes (stop_reason="end_turn") or max tool calls reached
"""

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


async def run_agent(
    messages: list[dict],
    session_id: str | None = None,
) -> AsyncGenerator[AgentEvent, None]:
    """Run the agent loop, yielding SSE events."""
    if not session_id:
        session_id = uuid.uuid4().hex[:16]

    # Validate API key before doing anything
    if not settings.anthropic_api_key or settings.anthropic_api_key.startswith("your-"):
        yield AgentEvent(type="error", data={
            "message": "Anthropic API key not configured. Set ANTHROPIC_API_KEY in your .env file."
        })
        return

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    anthropic_messages = []
    for msg in messages:
        anthropic_messages.append({
            "role": msg["role"],
            "content": msg["content"],
        })

    tool_call_count = 0
    max_calls = settings.agent_max_tool_calls

    while True:
        # ── Call Claude with streaming ──
        try:
            stream = client.messages.stream(
                model=settings.agent_model,
                max_tokens=settings.agent_max_tokens,
                temperature=settings.agent_temperature,
                system=SYSTEM_PROMPT,
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

        except anthropic.AuthenticationError:
            yield AgentEvent(type="error", data={
                "message": "Invalid Anthropic API key. Please check ANTHROPIC_API_KEY in your .env file."
            })
            return
        except anthropic.RateLimitError:
            yield AgentEvent(type="error", data={
                "message": "Anthropic API rate limit reached. Please wait a moment and try again."
            })
            return
        except anthropic.APIConnectionError as e:
            yield AgentEvent(type="error", data={
                "message": f"Cannot reach Anthropic API. Check your internet connection. ({e})"
            })
            return
        except Exception as e:
            logger.exception("Anthropic API error")
            yield AgentEvent(type="error", data={
                "message": f"API error: {type(e).__name__}: {str(e)[:200]}"
            })
            return

        # ── Collect content blocks ──
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

            # Emit tool_call event
            yield AgentEvent(type="tool_call", data={
                "name": tool_block.name,
                "input": tool_block.input,
            })

            # Execute the tool
            try:
                result = await execute_tool(tool_block.name, tool_block.input)
            except Exception as e:
                logger.exception(f"Tool execution error: {tool_block.name}")
                result = {"error": f"Tool '{tool_block.name}' failed: {str(e)[:200]}"}

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
                    yield AgentEvent(type="datasheet", data=result)

            tool_results_content.append({
                "type": "tool_result",
                "tool_use_id": tool_block.id,
                "content": result_str,
            })

        # Append tool results to message history for next loop iteration
        anthropic_messages.append({"role": "user", "content": tool_results_content})

    # ── Done ──
    yield AgentEvent(type="done", data={})
