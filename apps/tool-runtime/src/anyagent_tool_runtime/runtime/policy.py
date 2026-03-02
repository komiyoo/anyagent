from __future__ import annotations

from fnmatch import fnmatchcase
from typing import Any


def pattern_match(tool_name: str, pattern: str) -> bool:
    if pattern.endswith(".*") and "*" not in pattern[:-2] and "?" not in pattern[:-2]:
        return tool_name.startswith(pattern[:-1])
    return fnmatchcase(tool_name, pattern)


def is_allowed_by_policy(
    *,
    tool_name: str,
    category: str,
    context: dict[str, Any],
    allow_sandbox: bool,
) -> tuple[bool, str]:
    policy = context.get("policy") if isinstance(context.get("policy"), dict) else {}
    allow_patterns = policy.get("allow_tools") if isinstance(policy.get("allow_tools"), list) else None
    deny_patterns = policy.get("deny_tools") if isinstance(policy.get("deny_tools"), list) else None

    allow_list = [p for p in (allow_patterns or []) if isinstance(p, str) and p.strip()]
    deny_list = [p for p in (deny_patterns or []) if isinstance(p, str) and p.strip()]

    for pat in deny_list:
        if pattern_match(tool_name, pat):
            return False, "denied_by_policy"

    if category == "sandbox" and not allow_sandbox:
        return False, "sandbox_disabled"

    if allow_list:
        for pat in allow_list:
            if pattern_match(tool_name, pat):
                return True, "allowed_by_allowlist"
        return False, "not_in_allowlist"

    # 无 allowlist：默认最小暴露面（v0 安全基线）
    if category in ("core", "app"):
        return True, "default_allow_core_app"
    return False, "default_deny_channel_sandbox"

