from __future__ import annotations

from pathlib import Path

from anyagent.agent_runtime import SkillInjector, resolve_skill_injection_token_budget
from anyagent.skills import SkillEnablement
from anyagent.skills.models import SkillFrontMatter, SkillPackage


def _skill(tmp_path: Path, name: str, body: str) -> SkillPackage:
    skill_dir = tmp_path / name
    skill_dir.mkdir()
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(body, encoding="utf-8")
    return SkillPackage(
        skill_dir=skill_dir,
        skill_md_path=skill_md,
        scope="repo",
        frontmatter=SkillFrontMatter(name=name, description=f"{name} skill"),
        body_markdown=body,
    )


def test_skill_injector_selects_mentions_and_applies_budget(tmp_path: Path) -> None:
    small = _skill(tmp_path, "small-skill", "Use this small skill.")
    large = _skill(tmp_path, "large-skill", "x" * 400)

    result = SkillInjector(token_budget=140).select_for_request(
        skills=[small, large],
        enablement=SkillEnablement(user_disabled_paths=set()),
        body={"input": "please use $small-skill and $large-skill"},
    )

    assert [skill.frontmatter.name for skill in result.selected_skills] == ["small-skill"]
    assert any(decision.reason == "selected_by_unique_mention" for decision in result.selection_decisions)
    assert [warning.skill_stable_id for warning in result.budget_warnings] == [large.stable_id]
    assert result.estimated_tokens <= result.token_budget


def test_skill_injection_token_budget_resolves_metadata_before_env() -> None:
    assert (
        resolve_skill_injection_token_budget(
            metadata={"skill_injection_token_budget": "123"},
            env={"ANYAGENT_SKILL_INJECTION_TOKEN_BUDGET": "456"},
        )
        == 123
    )
    assert resolve_skill_injection_token_budget(metadata={}, env={"ANYAGENT_SKILL_INJECTION_TOKEN_BUDGET": "456"}) == 456
    assert resolve_skill_injection_token_budget(metadata={"skill_injection_token_budget": "bad"}, env={}, default=99) == 99
