from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping

from anyagent.protocol.context_fragments import render_context_fragment
from anyagent.skills import SkillEnablement
from anyagent.skills.models import SkillPackage
from anyagent.skills.selection import (
    SkillSelectionDecision,
    extract_user_texts_from_responses_request,
    select_skills,
)

from .prompt_envelope import build_skill_catalog_fragment


DEFAULT_SKILL_INJECTION_TOKEN_BUDGET = 8000
SKILL_INJECTION_TOKEN_BUDGET_ENV = "ANYAGENT_SKILL_INJECTION_TOKEN_BUDGET"


@dataclass(frozen=True)
class SkillInjectionBudgetWarning:
    skill_stable_id: str
    reason: str
    estimated_tokens: int
    budget_tokens: int


@dataclass(frozen=True)
class SkillInjectionResult:
    selected_skills: list[SkillPackage]
    selection_decisions: list[SkillSelectionDecision]
    budget_warnings: list[SkillInjectionBudgetWarning]
    token_budget: int
    estimated_tokens: int


class SkillInjector:
    """
    Standard Skill -> Agent Loop injection selector.

    It resolves default/structured/$skill mentions using the skills SSOT, then
    applies a coarse token budget before selected skills are handed to the
    prompt envelope builder.
    """

    def __init__(self, *, token_budget: int = DEFAULT_SKILL_INJECTION_TOKEN_BUDGET, chars_per_token: int = 4) -> None:
        self.token_budget = max(0, int(token_budget))
        self.chars_per_token = max(1, int(chars_per_token))

    def select_for_request(
        self,
        *,
        skills: list[SkillPackage],
        enablement: SkillEnablement,
        body: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        default_selected: list[str] | None = None,
    ) -> SkillInjectionResult:
        user_texts = extract_user_texts_from_responses_request(body)
        selected, decisions = select_skills(
            skills=skills,
            enablement=enablement,
            metadata=metadata if isinstance(metadata, dict) else None,
            user_texts=user_texts,
            default_selected=default_selected,
            allow_implicit_invocation=False,
        )
        return self.apply_budget(selected_skills=selected, selection_decisions=decisions)

    def apply_budget(
        self,
        *,
        selected_skills: list[SkillPackage],
        selection_decisions: list[SkillSelectionDecision] | None = None,
    ) -> SkillInjectionResult:
        kept: list[SkillPackage] = []
        warnings: list[SkillInjectionBudgetWarning] = []
        used = 0
        for skill in selected_skills:
            estimated = self.estimate_skill_tokens(skill)
            if used + estimated > self.token_budget:
                warnings.append(
                    SkillInjectionBudgetWarning(
                        skill_stable_id=skill.stable_id,
                        reason="skill_token_budget_exceeded",
                        estimated_tokens=estimated,
                        budget_tokens=self.token_budget,
                    )
                )
                continue
            kept.append(skill)
            used += estimated
        return SkillInjectionResult(
            selected_skills=kept,
            selection_decisions=list(selection_decisions or []),
            budget_warnings=warnings,
            token_budget=self.token_budget,
            estimated_tokens=used,
        )

    def estimate_skill_tokens(self, skill: SkillPackage) -> int:
        fragment = build_skill_catalog_fragment([skill], selected_skills=[skill])
        text = render_context_fragment(fragment) if fragment is not None else ""
        return max(1, (len(text) + self.chars_per_token - 1) // self.chars_per_token)


def resolve_skill_injection_token_budget(
    *,
    metadata: dict[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
    default: int = DEFAULT_SKILL_INJECTION_TOKEN_BUDGET,
) -> int:
    raw: Any = None
    if isinstance(metadata, dict):
        raw = metadata.get("skill_injection_token_budget")
    if raw is None:
        raw = (env or os.environ).get(SKILL_INJECTION_TOKEN_BUDGET_ENV)
    if raw is None:
        return default
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return default
