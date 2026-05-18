from __future__ import annotations

"""
Tool manifest extensions (SSOT).

AnyAgent uses OpenAI Responses-compatible `tools[]` shapes for model injection,
but may attach a few internal-only fields in Tool Runtime manifest responses.

Rules:
- Tool Runtime may emit internal extension fields (e.g., `x-anyagent-kind`) for
  server/client derivation logic.
- Agent API / SDK must strip these fields before forwarding tools to upstream
  model providers (OpenAI, etc.).
"""

import re
from typing import Any, Literal


AnyAgentToolKind = Literal["command", "mcp"]

_INTERNAL_TOOL_FIELDS = frozenset({"x-anyagent-kind", "x_anyagent_kind", "x-anyagent-source-name", "x_anyagent_source_name"})
_OPENAI_TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def tool_kind_from_tool_param(tool: dict[str, Any]) -> AnyAgentToolKind | None:
    """Read AnyAgent tool kind marker from a function tool param dict."""

    raw = tool.get("x-anyagent-kind")
    if raw is None:
        raw = tool.get("x_anyagent_kind")
    if raw == "command":
        return "command"
    if raw == "mcp":
        return "mcp"
    return None


def tool_kind_for_tool_name(tools: list[dict[str, Any]], tool_name: str) -> AnyAgentToolKind | None:
    """Find tool kind marker for a given tool name in a manifest tools list."""

    if not isinstance(tool_name, str) or not tool_name.strip():
        return None
    name = tool_name.strip()
    for t in tools:
        if not isinstance(t, dict) or t.get("type") != "function":
            continue
        n = t.get("name")
        if isinstance(n, str) and n == name:
            return tool_kind_from_tool_param(t)
    return None


def model_tool_name_for_name(name: str) -> str:
    """Return an OpenAI-compatible function name for an AnyAgent tool name."""

    value = name.strip()
    if _OPENAI_TOOL_NAME_RE.fullmatch(value):
        return value
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_")
    return normalized or "tool"


def build_model_tool_name_map(tools: list[dict[str, Any]]) -> dict[str, str]:
    """Build `model-visible name -> AnyAgent manifest name` for renamed tools."""

    out: dict[str, str] = {}
    used: set[str] = set()
    for tool in tools:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            continue
        raw_name = tool.get("name")
        if not isinstance(raw_name, str) or not raw_name.strip():
            continue
        source_name = raw_name.strip()
        model_name = model_tool_name_for_name(source_name)
        base = model_name
        suffix = 2
        while model_name in used:
            model_name = f"{base}_{suffix}"
            suffix += 1
        used.add(model_name)
        if model_name != source_name:
            out[model_name] = source_name
    return out


def source_tool_name_for_model_name(tools: list[dict[str, Any]], tool_name: str) -> str:
    """Map a model-visible function name back to the AnyAgent manifest tool name."""

    if not isinstance(tool_name, str) or not tool_name.strip():
        return tool_name
    name = tool_name.strip()
    mapped = build_model_tool_name_map(tools).get(name)
    if isinstance(mapped, str) and mapped.strip():
        return mapped
    for tool in tools:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            continue
        raw_name = tool.get("name")
        if not isinstance(raw_name, str) or not raw_name.strip():
            continue
        source_name = raw_name.strip()
        if name == source_name or name == model_tool_name_for_name(source_name):
            return source_name
    return name


def strip_internal_tool_fields(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Return a new `tools[]` list with AnyAgent internal fields removed.

    This should be used before forwarding `tools[]` to upstream model providers.
    """

    out: list[dict[str, Any]] = []
    used: set[str] = set()
    for t in tools:
        if not isinstance(t, dict):
            continue
        item = {k: v for k, v in t.items() if k not in _INTERNAL_TOOL_FIELDS}
        raw_name = item.get("name")
        if isinstance(raw_name, str) and raw_name.strip():
            model_name = model_tool_name_for_name(raw_name)
            base = model_name
            suffix = 2
            while model_name in used:
                model_name = f"{base}_{suffix}"
                suffix += 1
            used.add(model_name)
            item["name"] = model_name
            item["strict"] = False
        out.append(item)
    return out
