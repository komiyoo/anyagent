from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .loader import SkillLoadError, load_skill_package
from .models import SkillPackage, SkillScope


@dataclass(frozen=True)
class SkillRoot:
    scope: SkillScope
    root: Path


def dedupe_skills_by_name(skills: list[SkillPackage]) -> tuple[list[SkillPackage], list[tuple[str, str]]]:
    """
    默认不允许同名 skill 并存。

    调用方通过传入 skills 的顺序表达优先级：越靠前优先级越高，后续同名项会被跳过。
    """
    chosen_by_name: dict[str, SkillPackage] = {}
    unique_skills: list[SkillPackage] = []
    errors: list[tuple[str, str]] = []

    for skill in skills:
        name = skill.frontmatter.name.strip()
        kept = chosen_by_name.get(name)
        if kept is not None:
            errors.append(
                (
                    str(skill.skill_dir),
                    (
                        "duplicate skill name shadowed by higher-priority skill: "
                        f"name={name} kept={kept.skill_md_path} dropped={skill.skill_md_path}"
                    ),
                )
            )
            continue
        chosen_by_name[name] = skill
        unique_skills.append(skill)

    return unique_skills, errors


def default_skill_roots(*, workspace_dir: Path) -> list[SkillRoot]:
    """
    v0 建议的默认 roots（可由调用方覆盖）：
    - Repo: <workspace>/.agents/skills
    - User: ~/.agents/skills
    - System: /opt/agents/skills
    - Admin: <tenant_shared_dir>/skills（v0 先不在 SDK 内硬编码）
    """
    return [
        SkillRoot(scope="repo", root=Path(workspace_dir) / ".agents" / "skills"),
        SkillRoot(scope="user", root=Path.home() / ".agents" / "skills"),
        SkillRoot(scope="system", root=Path("/opt/agents/skills")),
    ]


def discover_skills(roots: list[SkillRoot]) -> tuple[list[SkillPackage], list[tuple[str, str]]]:
    """
    扫描并加载 roots 下的 skill packages。

    去重规则（v0）：
    - 同一个 `SKILL.md` 的 canonical path 只加载一次
    - 同名 skill 默认不并存：按 roots 顺序保留高优先级项，低优先级项记入 errors
    """
    loaded_paths: set[str] = set()
    loaded_skills: list[SkillPackage] = []
    errors: list[tuple[str, str]] = []

    for sr in roots:
        root = Path(sr.root)
        if not root.exists():
            continue

        for skill_md in sorted(root.rglob("SKILL.md"), key=lambda p: str(p)):
            if not skill_md.is_file():
                continue
            skill_dir = skill_md.parent
            key = str(skill_md.resolve())
            if key in loaded_paths:
                continue
            try:
                loaded_paths.add(key)
                loaded_skills.append(load_skill_package(skill_dir, scope=sr.scope))
            except SkillLoadError as e:
                errors.append((str(skill_dir), str(e)))

    skills, duplicate_errors = dedupe_skills_by_name(loaded_skills)
    errors.extend(duplicate_errors)
    return skills, errors
