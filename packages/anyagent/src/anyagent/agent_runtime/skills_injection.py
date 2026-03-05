from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from anyagent.protocol.openai_responses import inject_text_into_responses_body
from anyagent.skills.models import SkillPackage


SkillInjectionRole = Literal["developer", "system"]


@dataclass(frozen=True)
class SkillInjectionWarning:
    skill_stable_id: str | None
    reason: str


def build_skills_injection_text(skills: list[SkillPackage]) -> str:
    """
    req-12-6-2：将选中的 skills 注入本次 run 的上下文（developer/system role）。

    约束：
    - 注入内容必须包含 skill name/path（用于审计）+ SKILL.md body
    - 注入必须是 per-run 的（由调用方把结果拼到 request body.input）
    """
    blocks: list[str] = []
    for s in skills:
        sid = s.stable_id
        name = s.frontmatter.name
        blocks.append(
            "\n".join(
                [
                    "[anyagent Skill]",
                    f"name: {name}",
                    f"stable_id: {sid}",
                    "",
                    "[SKILL_BODY]",
                    (s.body_markdown or "").rstrip(),
                ]
            ).rstrip()
        )
    return "\n\n".join(blocks).strip()


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
