"""Convert messages between normalized (Anthropic-like) and OpenAI formats.

Normalized format (used for DB storage and as the canonical in-memory format):
  - Role "assistant" with content blocks:
      [{"type": "text", "text": "..."}, {"type": "tool_use", "id": "...", "name": "...", "input": {...}}, ...]
  - Role "user" with content blocks:
      [{"type": "tool_result", "tool_use_id": "...", "content": "..."}, ...]
  - Thinking blocks: {"type": "thinking", "thinking": "..."}

OpenAI format:
  - Role "assistant" with .content (text) and .tool_calls array:
      {"role": "assistant", "content": "text here", "tool_calls": [{"id": "...", "type": "function", "function": {"name": "...", "arguments": "{...}"}}]}
  - Role "tool" (one message per tool result):
      {"role": "tool", "tool_call_id": "...", "content": "..."}
  - System prompt: {"role": "system", "content": "..."}
  - No thinking blocks (stripped)
"""

from __future__ import annotations

import json


def normalized_to_openai(
    messages: list[dict],
    *,
    system: str | list[dict] | None = None,
) -> list[dict]:
    """Convert normalized (Anthropic-like) messages to OpenAI chat format.

    Args:
        messages:  Conversation in normalized format.
        system:    System prompt. If str, prepended as {"role": "system"}.
                   If list[dict] (Anthropic cached format), text is extracted.

    Returns:
        List of OpenAI-format messages.
    """
    result: list[dict] = []

    # Prepend system message
    if system:
        if isinstance(system, str):
            result.append({"role": "system", "content": system})
        elif isinstance(system, list):
            # Anthropic cached format: [{"type": "text", "text": "...", "cache_control": ...}]
            parts = []
            for block in system:
                if isinstance(block, dict) and block.get("text"):
                    parts.append(block["text"])
                elif isinstance(block, str):
                    parts.append(block)
            if parts:
                result.append({"role": "system", "content": "\n\n".join(parts)})

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content")

        if role == "assistant":
            openai_msg = _convert_assistant_message(content)
            result.append(openai_msg)

        elif role == "user":
            # Could be plain text or a list with tool_result blocks
            if isinstance(content, str):
                result.append({"role": "user", "content": content})
            elif isinstance(content, list):
                # Check if this is a pure tool_result message
                tool_results = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]
                text_blocks = [b for b in content if isinstance(b, dict) and b.get("type") == "text"]
                other_blocks = [
                    b for b in content
                    if isinstance(b, dict) and b.get("type") not in ("tool_result", "text", "thinking")
                ]

                # Emit tool result messages (role: "tool")
                for tr in tool_results:
                    tool_content = tr.get("content", "")
                    if isinstance(tool_content, list):
                        # Anthropic allows content as list of blocks
                        parts = []
                        for block in tool_content:
                            if isinstance(block, dict) and block.get("text"):
                                parts.append(block["text"])
                            elif isinstance(block, str):
                                parts.append(block)
                        tool_content = "\n".join(parts)
                    elif not isinstance(tool_content, str):
                        tool_content = json.dumps(tool_content)

                    result.append({
                        "role": "tool",
                        "tool_call_id": tr.get("tool_use_id", ""),
                        "content": tool_content,
                    })

                # If there were also text blocks, emit a user message
                if text_blocks:
                    text_parts = [b.get("text", "") for b in text_blocks if b.get("text")]
                    if text_parts:
                        result.append({"role": "user", "content": "\n".join(text_parts)})

            else:
                result.append({"role": "user", "content": str(content) if content else ""})

        else:
            # Pass through system or other roles
            if isinstance(content, str):
                result.append({"role": role, "content": content})
            elif isinstance(content, list):
                text = " ".join(
                    b.get("text", "") for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                )
                result.append({"role": role, "content": text})

    return result


def _convert_assistant_message(content) -> dict:
    """Convert an assistant message's content to OpenAI format.

    Anthropic: content is a list of blocks (text, tool_use, thinking).
    OpenAI:    content is a string + optional tool_calls array.
    """
    if isinstance(content, str):
        return {"role": "assistant", "content": content}

    if not isinstance(content, list):
        return {"role": "assistant", "content": str(content) if content else ""}

    text_parts: list[str] = []
    tool_calls: list[dict] = []

    for block in content:
        if not isinstance(block, dict):
            continue

        block_type = block.get("type", "")

        if block_type == "text":
            text_parts.append(block.get("text", ""))

        elif block_type == "tool_use":
            arguments = block.get("input", {})
            if isinstance(arguments, dict):
                arguments_str = json.dumps(arguments)
            else:
                arguments_str = str(arguments)

            tool_calls.append({
                "id": block.get("id", ""),
                "type": "function",
                "function": {
                    "name": block.get("name", ""),
                    "arguments": arguments_str,
                },
            })

        elif block_type == "thinking":
            # GLM/OpenAI has no thinking — skip
            pass

    msg: dict = {"role": "assistant", "content": "\n".join(text_parts) if text_parts else None}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return msg


def openai_response_to_normalized(
    content: str | None,
    tool_calls: list[dict] | None,
) -> list[dict]:
    """Convert an OpenAI assistant response to normalized content blocks.

    Used after receiving a completion from the OpenAI/GLM API to build the
    content list that goes into the normalized message history.

    Args:
        content:     The text content from the response (may be None)
        tool_calls:  The tool_calls array from the response (may be None/empty)

    Returns:
        List of normalized content blocks (text + tool_use).
    """
    blocks: list[dict] = []

    if content:
        blocks.append({"type": "text", "text": content})

    if tool_calls:
        for tc in tool_calls:
            func = tc.get("function", {})
            arguments_raw = func.get("arguments", "{}")

            # Parse arguments: OpenAI sends JSON string, we need dict
            if isinstance(arguments_raw, str):
                try:
                    arguments = json.loads(arguments_raw)
                except (json.JSONDecodeError, TypeError):
                    arguments = {"_raw_arguments": arguments_raw}
            else:
                arguments = arguments_raw

            blocks.append({
                "type": "tool_use",
                "id": tc.get("id", ""),
                "name": func.get("name", ""),
                "input": arguments,
            })

    return blocks
