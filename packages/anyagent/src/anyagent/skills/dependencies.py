from __future__ import annotations

from typing import Any

from .models import SkillPackage, SkillToolDependency


SUPPORTED_TRANSPORTS = {"core", "app", "sandbox", "channel", "mcp"}


def _normalize_dep(obj: Any) -> SkillToolDependency | None:
    if not isinstance(obj, dict):
        return None
    try:
        return SkillToolDependency.model_validate(obj)
    except Exception:  # noqa: BLE001
        return None


def _dep_to_requested_tools(dep: SkillToolDependency) -> list[str]:
    """
    将 skill dependency 归一成“希望披露”的工具名/模式。

    说明：
    - v0 允许返回 glob pattern（例如 `app.*`），由 Tool Runtime manifest 负责展开与最终收口。
    - `mcp` 为未来扩展：v0 暂不映射到 anyagent Tool Runtime tool name。
    """
    transport = (dep.transport or "").strip()
    value = (dep.value or "").strip()

    if transport not in SUPPORTED_TRANSPORTS:
        return []

    if transport == "mcp":
        return []

    if transport in {"core", "app", "sandbox"}:
        # value 若给出，则允许显式工具名或 pattern；否则按 namespace 全量请求
        return [value] if value else [f"{transport}.*"]

    if transport == "channel":
        # channel 依赖：value 期望是 namespace（例如 feishu/discord/telegram/web）或完整 tool 名/pattern
        if not value:
            return []
        if "." in value or "*" in value:
            return [value]
        return [f"{value}.*"]

    return []


def requested_tool_names_for_skill(skill: SkillPackage) -> list[str]:
    """
    从 `agents/openai.yaml` 里抽取 dependencies.tools 并映射到 requested_tool_names。
    解析失败时返回空列表（fail-open）。
    """
    meta = skill.agent_metadata
    if not isinstance(meta, dict):
        return []
    deps = meta.get("dependencies")
    if not isinstance(deps, dict):
        return []
    tools = deps.get("tools")
    if not isinstance(tools, list):
        return []

    out: list[str] = []
    for raw in tools:
        dep = _normalize_dep(raw)
        if dep is None:
            continue
        out.extend(_dep_to_requested_tools(dep))

    # 稳定去重
    uniq: list[str] = []
    seen: set[str] = set()
    for name in out:
        if not isinstance(name, str):
            continue
        n = name.strip()
        if not n or n in seen:
            continue
        seen.add(n)
        uniq.append(n)
    return uniq


def requested_tool_names_for_skills(skills: list[SkillPackage]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for s in skills:
        for n in requested_tool_names_for_skill(s):
            if n not in seen:
                seen.add(n)
                merged.append(n)
    return merged

