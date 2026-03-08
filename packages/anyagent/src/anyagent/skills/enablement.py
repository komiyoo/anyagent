from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .models import SkillPackage


def canonical_skill_md_path(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve())


def resolve_disabled_skill_stable_ids(
    raw_paths: Iterable[str] | None,
    *,
    skills: Iterable[SkillPackage],
    base_dir: str | Path | None = None,
) -> frozenset[str]:
    """Resolve disabled skill config into canonical visible skill stable ids."""
    if raw_paths is None:
        return frozenset()

    skills_by_name = {skill.frontmatter.name: skill for skill in skills}
    base_path = Path(base_dir).expanduser().resolve() if base_dir is not None else None
    disabled: set[str] = set()
    for raw in raw_paths:
        if not isinstance(raw, str) or not raw.strip():
            continue
        ref = raw.strip()
        matched = skills_by_name.get(ref)
        if matched is not None:
            disabled.add(matched.stable_id)
            continue
        if ref.startswith("skill://"):
            ref = ref[len("skill://") :]
        path = Path(ref).expanduser()
        if not path.is_absolute() and base_path is not None:
            path = base_path / path
        if path.name != "SKILL.md":
            continue
        disabled.add(canonical_skill_md_path(path))
    return frozenset(disabled)


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
