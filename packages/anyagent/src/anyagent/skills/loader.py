from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import SkillFrontMatter, SkillPackage, SkillScope


class SkillLoadError(Exception):
    pass


def _split_frontmatter(md_text: str) -> tuple[str | None, str]:
    """
    解析 YAML frontmatter（--- ... ---）。
    返回 (frontmatter_yaml_text, body_text)。
    """
    lines = md_text.splitlines(keepends=False)
    if not lines or lines[0].strip() != "---":
        return None, md_text

    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        raise SkillLoadError("frontmatter starts with '---' but no closing '---' found")

    fm = "\n".join(lines[1:end]).strip()
    body = "\n".join(lines[end + 1 :]).lstrip("\n")
    return fm, body


def _load_yaml_file_fail_open(path: Path) -> dict[str, Any] | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except Exception:  # noqa: BLE001
        return None

    try:
        data = yaml.safe_load(raw)
    except Exception:  # noqa: BLE001
        return None

    return data if isinstance(data, dict) else None


def load_skill_package(skill_dir: Path, *, scope: SkillScope) -> SkillPackage:
    """
    v0 约束：
    - `SKILL.md` 必须存在
    - `agents/openai.yaml` 解析失败必须 fail-open（忽略其元数据）
    """
    skill_dir = Path(skill_dir)
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        raise SkillLoadError(f"missing SKILL.md: {skill_md}")

    raw = skill_md.read_text(encoding="utf-8")
    fm_text, body = _split_frontmatter(raw)
    if fm_text is None:
        raise SkillLoadError("SKILL.md must contain YAML frontmatter (--- ... ---)")

    try:
        fm_obj = yaml.safe_load(fm_text)
    except Exception as e:  # noqa: BLE001
        raise SkillLoadError(f"invalid YAML frontmatter: {e}") from e
    if not isinstance(fm_obj, dict):
        raise SkillLoadError("frontmatter must be a YAML object")

    frontmatter = SkillFrontMatter.model_validate(fm_obj)
    if len(frontmatter.name) > 64:
        raise SkillLoadError("frontmatter.name too long (max 64)")
    if len(frontmatter.description) > 1024:
        raise SkillLoadError("frontmatter.description too long (max 1024)")

    agent_meta = _load_yaml_file_fail_open(skill_dir / "agents" / "openai.yaml")

    return SkillPackage(
        skill_dir=skill_dir,
        skill_md_path=skill_md,
        scope=scope,
        frontmatter=frontmatter,
        body_markdown=body,
        agent_metadata=agent_meta,
    )

