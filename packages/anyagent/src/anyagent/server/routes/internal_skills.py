from __future__ import annotations

import hashlib
from typing import Any

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, Response

from anyagent.config.agents import AgentCatalog
from anyagent.protocol.agent_api_internal import (
    InternalSkillListItem,
    InternalSkillLoadError,
    InternalSkillsListResponse,
)
from anyagent.skills import (
    SkillEnablement,
    dedupe_skills_by_name,
    requested_tool_names_for_skill,
    resolve_disabled_skill_stable_ids,
)
from anyagent.skills.models import SkillPackage

from anyagent.server.handlers.http_errors import check_bearer_api_key, openai_error_response
from anyagent.server.handlers.auth import _require_user_auth


def _skill_source_hash(skill: SkillPackage) -> str | None:
    try:
        return hashlib.sha256(skill.skill_md_path.read_bytes()).hexdigest()
    except Exception:  # noqa: BLE001
        return None


def _skill_interface(skill: SkillPackage) -> dict[str, Any] | None:
    metadata = skill.agent_metadata
    if not isinstance(metadata, dict):
        return None
    interface = metadata.get("interface")
    return interface if isinstance(interface, dict) else None


def create_internal_skills_router(
    *,
    api_key: str,
    catalog_state_attr: str = "agent_catalog",
    workspace_dir_state_attr: str = "workspace_dir",
    agent_skills_state_attr: str = "agent_skills",
    global_skills_state_attr: str = "global_skills",
    agent_skill_errors_state_attr: str = "agent_skill_errors",
    global_skill_errors_state_attr: str = "global_skill_errors",
) -> APIRouter:
    router = APIRouter()

    @router.get("/internal/skills/list", response_model=InternalSkillsListResponse)
    async def internal_skills_list(request: Request, agent_id: str = "main") -> Response | InternalSkillsListResponse:
        auth_err = await check_bearer_api_key(request, api_key=api_key)
        if auth_err is not None:
            return auth_err

        catalog: AgentCatalog = getattr(request.app.state, catalog_state_attr)
        pack = catalog.get(agent_id)
        if pack is None:
            return openai_error_response(404, message=f"unknown agent_id: {agent_id}", type_="invalid_request_error")

        agent_skills = getattr(request.app.state, agent_skills_state_attr, {})
        global_skills = getattr(request.app.state, global_skills_state_attr, [])
        all_skills, _duplicate_skills = dedupe_skills_by_name(
            [*agent_skills.get(agent_id, []), *global_skills]
        )

        disabled_paths = resolve_disabled_skill_stable_ids(
            pack.spec.skills.disabled_paths,
            skills=all_skills,
            base_dir=getattr(request.app.state, workspace_dir_state_attr),
        )
        enablement = SkillEnablement(user_disabled_paths=disabled_paths)

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
                    path=str(skill.skill_md_path.resolve()),
                    scope=skill.scope,
                    enabled=enablement.is_enabled(skill),
                    source_hash=_skill_source_hash(skill),
                    interface=_skill_interface(skill),
                    requested_tool_names=requested_tool_names_for_skill(skill),
                )
            )

        load_errors: list[InternalSkillLoadError] = []
        for path, reason in getattr(request.app.state, global_skill_errors_state_attr, []):
            load_errors.append(InternalSkillLoadError(scope="global", path=path, reason=reason))
        agent_skill_errors = getattr(request.app.state, agent_skill_errors_state_attr, {})
        for path, reason in agent_skill_errors.get(agent_id, []):
            load_errors.append(InternalSkillLoadError(scope="agent", path=path, reason=reason))

        return InternalSkillsListResponse(
            agent_id=agent_id,
            disabled_paths=sorted(disabled_paths),
            load_errors=load_errors,
            skills=skills_out,
        )

    return router


def create_builtin_internal_skills_router() -> APIRouter:
    router = APIRouter()

    @router.get("/internal/skills/list")
    async def internal_skills_list(
        req: Request,
        agent_id: str = "main",
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        state = req.app.state.anyagent
        _require_user_auth(state, authorization)
        resp = await state.runtime.list_skills(agent_id=agent_id)
        return JSONResponse(resp.model_dump(exclude_none=True))

    return router
