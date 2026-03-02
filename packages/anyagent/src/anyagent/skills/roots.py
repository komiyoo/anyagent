from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .loader import SkillLoadError, load_skill_package
from .models import SkillPackage, SkillScope


def iter_skill_dirs(root: Path) -> Iterable[Path]:
    """
    约定：root 下任意包含 SKILL.md 的目录即视为一个 skill package。
    """
    root = Path(root)
    if not root.exists():
        return []
    return {p.parent for p in root.rglob("SKILL.md") if p.is_file()}


def load_skills_from_root(root: Path, *, scope: SkillScope) -> tuple[list[SkillPackage], list[tuple[str, str]]]:
    """
    返回 (skills, errors)，errors 为 (path, reason)。
    """
    skills: list[SkillPackage] = []
    errors: list[tuple[str, str]] = []
    for d in sorted(iter_skill_dirs(root), key=lambda p: str(p)):
        try:
            skills.append(load_skill_package(d, scope=scope))
        except SkillLoadError as e:
            errors.append((str(d), str(e)))
    return skills, errors

