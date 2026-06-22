"""Convert tool definitions between Anthropic and OpenAI formats.

Anthropic (canonical format used in tools.py):
    {
        "name": "find_valves",
        "description": "...",
        "input_schema": { "type": "object", "properties": {...} }
    }

OpenAI / GLM:
    {
        "type": "function",
        "function": {
            "name": "find_valves",
            "description": "...",
            "parameters": { "type": "object", "properties": {...} }
        }
    }

The JSON Schema body (properties, required, etc.) is identical — only the
wrapper differs.
"""

from __future__ import annotations


def anthropic_to_openai_tools(tools: list[dict]) -> list[dict]:
    """Convert Anthropic tool definitions to OpenAI function-calling format.

    Strips Anthropic-specific keys (cache_control) that the OpenAI SDK
    would reject.
    """
    result = []
    for tool in tools:
        func_def: dict = {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
        }
        result.append({
            "type": "function",
            "function": func_def,
        })
    return result


def openai_to_anthropic_tools(tools: list[dict]) -> list[dict]:
    """Convert OpenAI function-calling tool definitions to Anthropic format.

    Inverse of anthropic_to_openai_tools.  Useful if tools were defined in
    OpenAI format first (unlikely in this project, but included for symmetry).
    """
    result = []
    for tool in tools:
        func = tool.get("function", {})
        result.append({
            "name": func.get("name", ""),
            "description": func.get("description", ""),
            "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
        })
    return result
