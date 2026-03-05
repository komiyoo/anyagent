from __future__ import annotations

from typing import Any

from anyagent.protocol.tool_manifest_extensions import strip_internal_tool_fields


def extract_allowed_function_tool_names(*, manifest_tools: list[dict[str, Any]]) -> set[str]:
    """Collect allowed function tool names from manifest tool definitions."""

    out: set[str] = set()
    for tool in manifest_tools:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            continue
        name = tool.get("name")
        if isinstance(name, str) and name.strip():
            out.add(name.strip())
    return out


def build_tool_loop_followup_body(
    *,
    previous_response_id: str,
    tool_outputs: list[Any],
    manifest_tools: list[dict[str, Any]],
    metadata: Any,
    tool_choice: Any,
    stream: bool | None,
    model: str | None = None,
) -> dict[str, Any]:
    """Build the next OpenAI Responses request body for one tool-loop turn."""

    next_body: dict[str, Any] = {
        "previous_response_id": previous_response_id,
        "input": tool_outputs,
        "tools": strip_internal_tool_fields(manifest_tools),
        "metadata": metadata,
    }
    if isinstance(model, str) and model.strip():
        next_body["model"] = model
    if stream is not None:
        next_body["stream"] = stream
    if tool_choice is not None:
        next_body["tool_choice"] = tool_choice
    return next_body
