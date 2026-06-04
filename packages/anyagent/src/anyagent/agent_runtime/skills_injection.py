from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from anyagent.agent_runtime.prompt_envelope import build_skill_catalog_fragment
from anyagent.protocol.context_fragments import render_context_fragment
from anyagent.protocol.openai_responses import inject_text_into_responses_body
from anyagent.skills.models import SkillPackage


SkillInjectionRole = Literal["developer", "system"]


@dataclass(frozen=True)
class SkillInjectionWarning:
    skill_stable_id: str | None
    reason: str


def build_skills_injection_text(skills: list[SkillPackage]) -> str:
    """
    将 skill metadata 注入本次 run 的上下文（developer/system role）。

    初始披露只包含 skill name/path/description 等 catalog 信息，不包含
    SKILL.md 正文；完整 skill 内容应通过后续显式加载路径按需披露。
    """
    fragment = build_skill_catalog_fragment(skills, selected_skills=skills)
    if fragment is None:
        return ""
    return render_context_fragment(fragment).strip()


def inject_skills_into_responses_body(
    *,
    body: dict[str, Any],
    selected_skills: list[SkillPackage],
    role: SkillInjectionRole = "developer",
) -> tuple[dict[str, Any], list[SkillInjectionWarning]]:
    """
    将 skills 注入到 OpenAI Responses 风格请求 body 中。
    - 注入位置：在 user message 之前（如已有 system/developer 前缀，则插在其后）
    - 注入失败（结构不支持等）fail-open：返回原 body + warning
    """
    if not selected_skills:
        return body, []

    warnings: list[SkillInjectionWarning] = []
    try:
        inj_text = build_skills_injection_text(selected_skills)
    except Exception as e:  # noqa: BLE001
        return body, [SkillInjectionWarning(skill_stable_id=None, reason=f"build_injection_failed: {e}")]

    if not inj_text:
        return body, [SkillInjectionWarning(skill_stable_id=None, reason="empty_injection_text")]

    body2 = inject_text_into_responses_body(body=body, text=inj_text, role=role)
    if body2 is body:
        warnings.append(SkillInjectionWarning(skill_stable_id=None, reason="unsupported_body.input_shape"))
        return body, warnings
    return body2, warnings
