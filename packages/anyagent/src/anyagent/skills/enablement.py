from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .models import SkillPackage


def canonical_skill_md_path(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve())


@dataclass(frozen=True)
class SkillEnablement:
    """
    v0 enable/disable：以 SKILL.md 的 canonical path 为 key。
    """

    user_disabled_paths: frozenset[str]
    session_disabled_paths: frozenset[str] = frozenset()
    session_enabled_paths: frozenset[str] = frozenset()

    def is_enabled(self, skill: SkillPackage) -> bool:
        sid = skill.stable_id
        # 安全优先：disabled 优先生效
        if sid in self.session_disabled_paths:
            return False
        if sid in self.session_enabled_paths:
            return True
        if sid in self.user_disabled_paths:
            return False
        return True


def filter_enabled_skills(
    skills: list[SkillPackage],
    *,
    enablement: SkillEnablement,
) -> tuple[list[SkillPackage], list[SkillPackage]]:
    enabled: list[SkillPackage] = []
    disabled: list[SkillPackage] = []
    for s in skills:
        (enabled if enablement.is_enabled(s) else disabled).append(s)
    return enabled, disabled

