from __future__ import annotations

from typing import Any

from anyagent.protocol.tool_runtime import PolicyHint, ToolContext

from .models import SkillPackage


def _normalize_str_list(obj: Any) -> list[str]:
    if obj is None:
        return []
    if isinstance(obj, str):
        s = obj.strip()
        return [s] if s else []
    if isinstance(obj, list):
        out: list[str] = []
        for v in obj:
            if isinstance(v, str):
                s = v.strip()
                if s:
                    out.append(s)
        return out
    return []


def _dedupe_stable(items: list[str]) -> list[str]:
    uniq: list[str] = []
    seen: set[str] = set()
    for it in items:
        s = it.strip()
        if not s or s in seen:
            continue
        seen.add(s)
        uniq.append(s)
    return uniq


def _extract_fs_roots(permissions: dict[str, Any]) -> tuple[list[str], list[str]]:
    """
    v0：尽量宽松解析 skill permissions 中的文件系统读写 roots。

    支持形态（任意一种即可）：
    - permissions.fs.read_roots / permissions.fs.write_roots
    - permissions.fs.read / permissions.fs.write
    - permissions.fs_read_roots / permissions.fs_write_roots
    - permissions.read_roots / permissions.write_roots
    """
    fs = permissions.get("fs") if isinstance(permissions.get("fs"), dict) else {}

    read_roots = _normalize_str_list(
        fs.get("read_roots")
        or fs.get("readRoots")
        or fs.get("read")
        or permissions.get("fs_read_roots")
        or permissions.get("fsReadRoots")
        or permissions.get("read_roots")
        or permissions.get("readRoots")
    )
    write_roots = _normalize_str_list(
        fs.get("write_roots")
        or fs.get("writeRoots")
        or fs.get("write")
        or permissions.get("fs_write_roots")
        or permissions.get("fsWriteRoots")
        or permissions.get("write_roots")
        or permissions.get("writeRoots")
    )

    return _dedupe_stable(read_roots), _dedupe_stable(write_roots)


def _extract_network_profile(permissions: dict[str, Any]) -> dict[str, Any] | None:
    """
    v0：network 权限档案先保留为“透传”结构，Tool Runtime / sandbox executor 再做二次收口。
    """
    n = permissions.get("network")
    if isinstance(n, dict):
        # 避免携带非 JSON 兼容对象
        return {k: v for k, v in n.items() if isinstance(k, str)}
    if isinstance(n, bool):
        return {"enabled": n}
    if isinstance(n, str):
        s = n.strip().lower()
        if s in {"none", "disabled", "false"}:
            return {"enabled": False}
        if s in {"all", "enabled", "true"}:
            return {"enabled": True}
    return None


def _network_explicitly_disabled(network: dict[str, Any] | None) -> bool:
    if not isinstance(network, dict):
        return False
    enabled = network.get("enabled")
    return enabled is False


def compile_policy_hint_from_permissions(permissions: dict[str, Any]) -> PolicyHint | None:
    """
    将 skill permissions 编译成 Tool Runtime 可理解的 policy hint（allow/deny tools pattern）。

    约束：
    - allow/deny 只是“提示”，Tool Runtime 必须基于更高层策略再次收口
    - v0 只做最小交互：在需要 sandbox 能力时显式 allow `sandbox.*`
    """
    read_roots, write_roots = _extract_fs_roots(permissions)
    network = _extract_network_profile(permissions)

    allow_tools: list[str] = []
    deny_tools: list[str] = []

    needs_sandbox = bool(read_roots or write_roots or permissions.get("sandbox") is not None)
    if needs_sandbox:
        # 一旦显式给 allowlist，Tool Runtime 会进入“仅 allowlist”模式；
        # 因此必须包含 core/app 的默认允许集合，避免无意收窄。
        allow_tools.extend(["core.*", "app.*", "sandbox.*"])

    if _network_explicitly_disabled(network):
        # v0：先做最小可用的“收缩工具暴露面”。
        # 后续如需更精细的 network->tools 映射，再在 tool registry 维护权威表。
        deny_tools.append("core.web_*")

    allow_tools = _dedupe_stable(allow_tools)
    deny_tools = _dedupe_stable(deny_tools)
    if not allow_tools and not deny_tools:
        return None
    return PolicyHint(allow_tools=allow_tools or None, deny_tools=deny_tools or None)


def compile_context_overrides_from_permissions(permissions: dict[str, Any]) -> dict[str, Any] | None:
    """
    将 skill permissions 编译为 ToolContext 的扩展字段（sandbox/network/fs roots）。
    Tool Runtime / sandbox executor 需要二次校验并强制上限。
    """
    read_roots, write_roots = _extract_fs_roots(permissions)
    network = _extract_network_profile(permissions)

    sandbox_profile: dict[str, Any] = {}
    if read_roots:
        sandbox_profile["fs_read_roots"] = read_roots
    if write_roots:
        sandbox_profile["fs_write_roots"] = write_roots
    if network is not None:
        sandbox_profile["network"] = network

    if not sandbox_profile:
        return None
    return {"sandbox": sandbox_profile}


def _merge_policy(base: PolicyHint | None, add: PolicyHint | None) -> PolicyHint | None:
    if base is None:
        return add
    if add is None:
        return base

    allow = _dedupe_stable([*(base.allow_tools or []), *(add.allow_tools or [])])
    deny = _dedupe_stable([*(base.deny_tools or []), *(add.deny_tools or [])])
    if not allow and not deny:
        return None
    return PolicyHint(allow_tools=allow or None, deny_tools=deny or None)


def _merge_sandbox_profiles(base: dict[str, Any] | None, add: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(base, dict):
        base = None
    if not isinstance(add, dict):
        add = None
    if base is None:
        return add
    if add is None:
        return base

    out = dict(base)
    # roots：union + stable dedupe
    out["fs_read_roots"] = _dedupe_stable(
        [*_normalize_str_list(base.get("fs_read_roots")), *_normalize_str_list(add.get("fs_read_roots"))]
    ) or None
    out["fs_write_roots"] = _dedupe_stable(
        [*_normalize_str_list(base.get("fs_write_roots")), *_normalize_str_list(add.get("fs_write_roots"))]
    ) or None
    # network：v0 简化，后写覆盖先写（更具体的 skill 后应用可以覆盖）
    if "network" in add:
        out["network"] = add.get("network")
    return {k: v for k, v in out.items() if v is not None}


def apply_permissions_to_tool_context(context: ToolContext, *, permissions: dict[str, Any]) -> ToolContext:
    """
    将单个 skill 的 permissions 应用到 ToolContext：
    - 合并 policy allow/deny tools pattern
    - 合并 sandbox profile（fs read/write roots + network）
    """
    add_policy = compile_policy_hint_from_permissions(permissions)
    add_overrides = compile_context_overrides_from_permissions(permissions) or {}

    base_dump = context.model_dump(exclude_none=True)
    base_policy = context.policy
    merged_policy = _merge_policy(base_policy, add_policy)
    if merged_policy is not None:
        base_dump["policy"] = merged_policy.model_dump(exclude_none=True)

    if "sandbox" in add_overrides:
        merged_sandbox = _merge_sandbox_profiles(base_dump.get("sandbox"), add_overrides.get("sandbox"))
        if merged_sandbox is not None:
            base_dump["sandbox"] = merged_sandbox

    return ToolContext.model_validate(base_dump)


def apply_skill_permissions_to_tool_context(context: ToolContext, *, skill: SkillPackage) -> ToolContext:
    """
    从 skill 的 `agents/openai.yaml` 中抽取 permissions 并应用到 ToolContext。
    解析失败时 fail-open（返回原 context）。
    """
    meta = skill.agent_metadata
    if not isinstance(meta, dict):
        return context
    perms = meta.get("permissions")
    if not isinstance(perms, dict):
        return context
    try:
        return apply_permissions_to_tool_context(context, permissions=perms)
    except Exception:  # noqa: BLE001
        return context


def apply_skills_permissions_to_tool_context(context: ToolContext, *, skills: list[SkillPackage]) -> ToolContext:
    merged = context
    for s in skills:
        merged = apply_skill_permissions_to_tool_context(merged, skill=s)
    return merged

