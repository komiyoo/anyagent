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

from typing import Any, Literal


AnyAgentToolKind = Literal["command", "mcp"]

_INTERNAL_TOOL_FIELDS = frozenset({"x-anyagent-kind", "x_anyagent_kind"})


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


def strip_internal_tool_fields(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Return a new `tools[]` list with AnyAgent internal fields removed.

    This should be used before forwarding `tools[]` to upstream model providers.
    """

    out: list[dict[str, Any]] = []
    for t in tools:
        if not isinstance(t, dict):
            continue
        out.append({k: v for k, v in t.items() if k not in _INTERNAL_TOOL_FIELDS})
    return out
