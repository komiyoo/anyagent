from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .loader import SkillLoadError, load_skill_package
from .models import SkillPackage, SkillScope


@dataclass(frozen=True)
class SkillRoot:
    scope: SkillScope
    root: Path


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
    - 同名 skill 允许存在多个来源（由上层 UI/选择逻辑处理稳定 key）
    """
    loaded: dict[str, SkillPackage] = {}
    errors: list[tuple[str, str]] = []

    for sr in roots:
        root = Path(sr.root)
        if not root.exists():
            continue

        for skill_md in root.rglob("SKILL.md"):
            if not skill_md.is_file():
                continue
            skill_dir = skill_md.parent
            key = str(skill_md.resolve())
            if key in loaded:
                continue
            try:
                loaded[key] = load_skill_package(skill_dir, scope=sr.scope)
            except SkillLoadError as e:
                errors.append((str(skill_dir), str(e)))

    # 按 path 稳定排序，方便可复现
    skills = [loaded[k] for k in sorted(loaded.keys())]
    return skills, errors

