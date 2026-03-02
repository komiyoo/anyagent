from __future__ import annotations

from typing import Any

from anyagent.tool_runtime.models import ToolDefinition
from anyagent.tool_runtime.registry import ToolRegistry

from .policy import is_allowed_by_policy


def to_openai_function_tool(td: ToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": td.name,
            "description": td.description or "",
            "parameters": td.parameters,
        },
    }


def _matches_requested(name: str, patterns: list[str]) -> bool:
    for p in patterns:
        p = p.strip()
        if not p:
            continue
        # 精确名优先
        if "*" not in p and "?" not in p and "[" not in p:
            if name == p:
                return True
            continue
        # glob pattern
        from fnmatch import fnmatchcase

        if fnmatchcase(name, p):
            return True
    return False


def build_manifest(
    *,
    registry: ToolRegistry,
    requested_tool_names: list[str] | None,
    allow_sandbox: bool,
    context: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[tuple[str, str, str]] | None]:
    tools = registry.list_tools()

    decisions: list[tuple[str, str, str]] | None = None

    if requested_tool_names is not None:
        decisions = []
        tools = [t for t in tools if _matches_requested(t.name, requested_tool_names)]

    out: list[dict[str, Any]] = []
    for td in tools:
        allowed, reason = is_allowed_by_policy(
            tool_name=td.name,
            category=td.category,
            context=context or {},
            allow_sandbox=allow_sandbox,
        )
        if not allowed:
            if decisions is not None:
                decisions.append((td.name, "deny", reason))
            continue
        if decisions is not None:
            decisions.append((td.name, "allow", reason))
        out.append(to_openai_function_tool(td))
    return out, decisions
