from __future__ import annotations

import json
import re
from typing import Any

_MCP_TOOL_NAME_ALLOWED_RE = re.compile(r"^[a-z0-9_.-]+$")
_MCP_TOOL_NAME_INVALID_CHARS_RE = re.compile(r"[^a-z0-9_.-]+")


def mcp_tool_to_function_param(tool: Any, server_label: str) -> dict[str, Any]:
    """Converts an MCP tool definition into an OpenAI function tool parameter."""
    tool_name = str(_field(tool, "name", default="")).strip()
    if not tool_name:
        raise ValueError("mcp tool missing name")
    sanitized_tool_name = sanitize_mcp_tool_name(tool_name)

    schema_raw = _field(tool, "input_schema", "inputSchema", default={})
    schema = _json_object(schema_raw)
    if "properties" not in schema or not isinstance(schema.get("properties"), dict):
        schema["properties"] = {}

    return {
        "type": "function",
        "name": f"mcp.{server_label}.{sanitized_tool_name}",
        "description": str(_field(tool, "description", default="") or ""),
        "parameters": schema,
        "x_anyagent_kind": "mcp",
        "x_anyagent_source_name": tool_name,
    }


def sanitize_mcp_tool_name(name: str) -> str:
    """Sanitizes an MCP tool name for OpenAI function-tool compatibility."""
    text = str(name).strip().lower()
    text = _MCP_TOOL_NAME_INVALID_CHARS_RE.sub("_", text).strip("_")
    if not text:
        raise ValueError("mcp tool name sanitizes to empty")
    if not _MCP_TOOL_NAME_ALLOWED_RE.match(text):
        raise ValueError(f"invalid sanitized mcp tool name: {text}")
    return text


def mcp_call_result_to_output_text(result: Any) -> str:
    """Converts an MCP CallToolResult into model-consumable text output."""
    blocks = _field(result, "content", default=[])
    if not isinstance(blocks, list):
        blocks = []

    parts: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            block = _model_dump(block)
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text" and isinstance(block.get("text"), str):
            parts.append(block["text"])
            continue
        parts.append(json.dumps(block, ensure_ascii=False, separators=(",", ":")))

    structured = _field(result, "structured_content", "structuredContent")
    if isinstance(structured, dict):
        parts.append(json.dumps(structured, ensure_ascii=False, separators=(",", ":")))

    if parts:
        return "\n".join(p for p in parts if p)

    is_error = bool(_field(result, "is_error", "isError", default=False))
    if is_error:
        return json.dumps({"is_error": True}, ensure_ascii=False, separators=(",", ":"))
    return ""


def _field(obj: Any, *names: str, default: Any = None) -> Any:
    """Reads one of several field names from a model or dict object."""
    for name in names:
        if isinstance(obj, dict) and name in obj:
            return obj[name]
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def _model_dump(obj: Any) -> dict[str, Any] | None:
    """Serializes a pydantic model-like object to a Python dict."""
    if hasattr(obj, "model_dump"):
        try:
            data = obj.model_dump(by_alias=True, exclude_none=True)
        except Exception:
            data = obj.model_dump()
        return data if isinstance(data, dict) else None
    return obj if isinstance(obj, dict) else None


def _json_object(value: Any) -> dict[str, Any]:
    """Normalizes arbitrary schema objects into a safe JSON object."""
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump"):
        dumped = _model_dump(value)
        if isinstance(dumped, dict):
            return dumped
    return {"type": "object", "properties": {}}
