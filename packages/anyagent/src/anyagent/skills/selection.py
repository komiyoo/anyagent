from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .enablement import SkillEnablement, canonical_skill_md_path, filter_enabled_skills
from .models import SkillPackage


SkillSelectionSource = Literal["agentspec", "structured", "mention", "implicit"]


@dataclass(frozen=True)
class SkillSelectionDecision:
    source: SkillSelectionSource
    raw: str
    selected: bool
    reason: str
    skill_stable_id: str | None = None


_MENTION_RE = re.compile(r"(?:^|\s)\$(?P<name>[a-zA-Z0-9_.-]{1,64})(?=\s|$)")


def _parse_metadata_skills(metadata: dict[str, Any] | None) -> tuple[list[str], list[SkillSelectionDecision]]:
    """
    req-12-6-1（structured）：
    - `metadata.skills` 为 JSON string，内容为 string list
    - v0 兼容：也允许直接传 list[str]
    """
    if not isinstance(metadata, dict):
        return [], []

    raw = metadata.get("skills")
    if raw is None:
        return [], []

    if isinstance(raw, list):
        out = [x for x in raw if isinstance(x, str) and x.strip()]
        return out, []

    if not isinstance(raw, str) or not raw.strip():
        return [], [SkillSelectionDecision(source="structured", raw=str(raw), selected=False, reason="invalid_metadata.skills")]

    try:
        obj = json.loads(raw)
    except Exception:  # noqa: BLE001
        return [], [SkillSelectionDecision(source="structured", raw=raw, selected=False, reason="metadata.skills_not_json")]

    if not isinstance(obj, list):
        return [], [SkillSelectionDecision(source="structured", raw=raw, selected=False, reason="metadata.skills_not_list")]

    out: list[str] = []
    for x in obj:
        if isinstance(x, str) and x.strip():
            out.append(x.strip())
    return out, []


def _canonicalize_skill_ref(s: str) -> str | None:
    """
    将 structured skills 的某些写法归一成 stable_id（canonical SKILL.md path）。
    支持：
    - "skill:///abs/path/to/SKILL.md"
    - "/abs/path/to/SKILL.md" 或 "~/.../SKILL.md"
    - "relative/path/to/SKILL.md"
    - "skill://<dir>"（若指向目录，则取其下 SKILL.md）
    """
    s = s.strip()
    if not s:
        return None

    if s.startswith("skill://"):
        s = s[len("skill://") :]

    p = Path(s).expanduser()
    # directory -> SKILL.md
    if str(p).endswith("/"):
        p = p / "SKILL.md"
    if p.name != "SKILL.md" and p.suffix != ".md":
        # 不强行猜测：避免把 name 当 path
        return None
    if p.name != "SKILL.md":
        return None

    return canonical_skill_md_path(p)


def extract_skill_mentions_from_text(text: str) -> list[str]:
    if not isinstance(text, str) or not text.strip():
        return []
    return [m.group("name") for m in _MENTION_RE.finditer(text)]


def extract_user_texts_from_responses_request(body: dict[str, Any]) -> list[str]:
    """
    从 OpenAI Responses 风格 body 中尽量提取 user text，用于 `$skill-name` mention。
    v0 为 best-effort：解析失败则返回空列表（fail-open）。
    """
    if not isinstance(body, dict):
        return []

    inp = body.get("input")
    if isinstance(inp, str):
        return [inp]

    if not isinstance(inp, list):
        return []

    out: list[str] = []
    for item in inp:
        if not isinstance(item, dict):
            continue
        if item.get("role") != "user":
            continue
        content = item.get("content")
        if isinstance(content, str) and content.strip():
            out.append(content)
            continue
        if isinstance(content, list):
            for part in content:
                if isinstance(part, str) and part.strip():
                    out.append(part)
                elif isinstance(part, dict):
                    t = part.get("type")
                    if t in {"input_text", "text"} and isinstance(part.get("text"), str) and part["text"].strip():
                        out.append(part["text"])

    return out


def select_skills(
    *,
    skills: list[SkillPackage],
    enablement: SkillEnablement,
    metadata: dict[str, Any] | None,
    user_texts: list[str] | None = None,
    default_selected: list[str] | None = None,
    allow_implicit_invocation: bool = False,
) -> tuple[list[SkillPackage], list[SkillSelectionDecision]]:
    """
    req-12-6-1：技能选择（按优先级）
    1) AgentSpec 默认技能（default_selected）
    2) structured metadata.skills
    3) $skill-name mention（仅唯一且 enabled）
    4) 隐式触发（v0 可选；此处仅保留开关，不默认实现策略）
    """
    enabled, _disabled = filter_enabled_skills(skills, enablement=enablement)
    enabled_by_id = {s.stable_id: s for s in enabled}
    enabled_by_name: dict[str, list[SkillPackage]] = {}
    for s in enabled:
        enabled_by_name.setdefault(s.frontmatter.name, []).append(s)

    selected: list[SkillPackage] = []
    selected_ids: set[str] = set()
    decisions: list[SkillSelectionDecision] = []

    structured, parse_decisions = _parse_metadata_skills(metadata)
    decisions.extend(parse_decisions)

    def apply_structured(raw_items: list[str], *, source: SkillSelectionSource) -> None:
        for raw in raw_items:
            if not isinstance(raw, str) or not raw.strip():
                continue

            ref_id = _canonicalize_skill_ref(raw)
            if ref_id is not None:
                s = enabled_by_id.get(ref_id)
                if s is None:
                    decisions.append(
                        SkillSelectionDecision(
                            source=source,
                            raw=raw,
                            selected=False,
                            reason="skill_not_found_or_disabled",
                            skill_stable_id=ref_id,
                        )
                    )
                    continue
                if s.stable_id not in selected_ids:
                    selected.append(s)
                    selected_ids.add(s.stable_id)
                decisions.append(
                    SkillSelectionDecision(
                        source=source,
                        raw=raw,
                        selected=True,
                        reason="selected_by_path",
                        skill_stable_id=s.stable_id,
                    )
                )
                continue

            # name-based
            name = raw.strip()
            cands = enabled_by_name.get(name) or []
            if len(cands) == 1:
                s = cands[0]
                if s.stable_id not in selected_ids:
                    selected.append(s)
                    selected_ids.add(s.stable_id)
                decisions.append(
                    SkillSelectionDecision(
                        source=source,
                        raw=raw,
                        selected=True,
                        reason="selected_by_unique_name",
                        skill_stable_id=s.stable_id,
                    )
                )
            elif len(cands) == 0:
                decisions.append(
                    SkillSelectionDecision(source=source, raw=raw, selected=False, reason="skill_not_found_or_disabled")
                )
            else:
                decisions.append(SkillSelectionDecision(source=source, raw=raw, selected=False, reason="ambiguous_name"))

    # 1) AgentSpec defaults
    apply_structured(default_selected or [], source="agentspec")
    # 2) structured metadata.skills
    apply_structured(structured, source="structured")

    # 2) mention
    texts = user_texts or []
    for text in texts:
        for token in extract_skill_mentions_from_text(text):
            cands = enabled_by_name.get(token) or []
            if len(cands) == 1:
                s = cands[0]
                if s.stable_id not in selected_ids:
                    selected.append(s)
                    selected_ids.add(s.stable_id)
                decisions.append(
                    SkillSelectionDecision(
                        source="mention",
                        raw=f"${token}",
                        selected=True,
                        reason="selected_by_unique_mention",
                        skill_stable_id=s.stable_id,
                    )
                )
            elif len(cands) == 0:
                decisions.append(SkillSelectionDecision(source="mention", raw=f"${token}", selected=False, reason="not_found"))
            else:
                decisions.append(SkillSelectionDecision(source="mention", raw=f"${token}", selected=False, reason="ambiguous"))

    # 3) implicit (optional; v0 不强制实现)
    if allow_implicit_invocation and allow_implicit_invocation is not False:
        decisions.append(
            SkillSelectionDecision(
                source="implicit",
                raw="",
                selected=False,
                reason="implicit_invocation_not_implemented",
            )
        )

    return selected, decisions
