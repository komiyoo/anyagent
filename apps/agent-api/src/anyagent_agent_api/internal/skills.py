from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from anyagent.agent_packs import AgentCatalog
from anyagent.skills import SkillEnablement, canonical_skill_md_path, requested_tool_names_for_skill
from anyagent.skills.models import SkillPackage

from ..auth import check_api_key
from ..errors import openai_error
from ..settings import Settings


class InternalSkillListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stable_id: str
    name: str
    description: str | None = None
    short_description: str | None = None
    scope: str
    enabled: bool
    requested_tool_names: list[str] = Field(default_factory=list)


class InternalSkillLoadError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["global", "agent"]
    path: str
    reason: str


class InternalSkillsListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    disabled_paths: list[str] = Field(default_factory=list)
    load_errors: list[InternalSkillLoadError] = Field(default_factory=list)
    skills: list[InternalSkillListItem] = Field(default_factory=list)


def create_internal_skills_router(settings: Settings) -> APIRouter:
    router = APIRouter()

    @router.get("/internal/skills/list", response_model=InternalSkillsListResponse)
    async def internal_skills_list(request: Request, agent_id: str = "main") -> Response | InternalSkillsListResponse:
        auth_err = await check_api_key(request, settings)
        if auth_err is not None:
            return auth_err

        catalog: AgentCatalog = request.app.state.agent_catalog
        pack = catalog.get(agent_id)
        if pack is None:
            return openai_error(404, message=f"unknown agent_id: {agent_id}", type_="invalid_request_error")

        all_skills: list[SkillPackage] = list(request.app.state.global_skills) + list(
            request.app.state.agent_skills.get(agent_id, [])
        )

        disabled_paths: set[str] = set()
        for raw in pack.spec.skills.disabled_paths or []:
            if not isinstance(raw, str) or not raw.strip():
                continue
            s = raw.strip()
            if s.startswith("skill://"):
                s = s[len("skill://") :]
            p = Path(s).expanduser()
            if p.name != "SKILL.md":
                continue
            disabled_paths.add(canonical_skill_md_path(p))

        enablement = SkillEnablement(user_disabled_paths=frozenset(disabled_paths))

        skills_out: list[InternalSkillListItem] = []
        for skill in all_skills:
            short_description = None
            if skill.frontmatter.metadata is not None:
                short_description = skill.frontmatter.metadata.short_description
            skills_out.append(
                InternalSkillListItem(
                    stable_id=skill.stable_id,
                    name=skill.frontmatter.name,
                    description=skill.frontmatter.description,
                    short_description=short_description,
                    scope=skill.scope,
                    enabled=enablement.is_enabled(skill),
                    requested_tool_names=requested_tool_names_for_skill(skill),
                )
            )

        load_errors: list[InternalSkillLoadError] = []
        for path, reason in request.app.state.global_skill_errors:
            load_errors.append(InternalSkillLoadError(scope="global", path=path, reason=reason))
        for path, reason in request.app.state.agent_skill_errors.get(agent_id, []):
            load_errors.append(InternalSkillLoadError(scope="agent", path=path, reason=reason))

        return InternalSkillsListResponse(
            agent_id=agent_id,
            disabled_paths=sorted(disabled_paths),
            load_errors=load_errors,
            skills=skills_out,
        )

    return router
