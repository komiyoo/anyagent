from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from anyagent.config.agents import AgentPack
from anyagent.agent_runtime.scripted_reply import (
    ScriptedReplyLoadError,
    ScriptedReplyMatch,
    ScriptedReplyProvider,
    ScriptedReplyRequest,
    load_scripted_reply_provider_from_classpath,
    resolve_scripted_reply,
)
from anyagent.protocol.tool_runtime import ToolContext
from anyagent.skills.models import SkillPackage

from .context_providers import _workspace_import_paths

_LOGGER = logging.getLogger(__name__)

ScriptedReplyResolver = Callable[[list[dict[str, Any]]], Awaitable[ScriptedReplyMatch | None]]


def _load_scripted_reply_providers_for_pack(*, pack: AgentPack, workspace_dir: Path) -> list[ScriptedReplyProvider]:
    configured = [
        item.strip()
        for item in (pack.spec.runtime.scripted_reply_providers or [])
        if isinstance(item, str) and item.strip()
    ]
    providers: list[ScriptedReplyProvider] = []
    if not configured:
        return providers

    with _workspace_import_paths(workspace_dir):
        for classpath in configured:
            try:
                providers.append(load_scripted_reply_provider_from_classpath(classpath))
            except ScriptedReplyLoadError as e:
                _LOGGER.warning("skipping scripted reply provider %r for agent %r: %s", classpath, pack.agent_id, e)
    return providers


def _build_scripted_reply_resolver(
    *,
    pack: AgentPack,
    agent_id: str,
    session_key: str | None,
    body: dict[str, Any],
    metadata: dict[str, Any] | None,
    workspace_dir: Path,
    tool_context: ToolContext,
    selected_skills: list[SkillPackage],
) -> ScriptedReplyResolver | None:
    """Return a resolver bound to this request, or ``None`` when no provider is configured.

    The resolver takes the session's previous transcript items (only known once
    the worker holds the session lease) and runs providers inside the workspace
    import path so provider modules can import their own helpers.
    """

    providers = _load_scripted_reply_providers_for_pack(pack=pack, workspace_dir=workspace_dir)
    if not providers:
        return None

    async def _resolve(previous_transcript_items: list[dict[str, Any]]) -> ScriptedReplyMatch | None:
        request = ScriptedReplyRequest(
            agent_id=agent_id,
            session_key=session_key,
            body=body,
            metadata=metadata,
            workspace_dir=workspace_dir,
            pack=pack,
            tool_context=tool_context,
            selected_skills=selected_skills,
            previous_transcript_items=list(previous_transcript_items),
        )
        with _workspace_import_paths(workspace_dir):
            return await resolve_scripted_reply(
                providers,
                request,
                warn=lambda message: _LOGGER.warning("agent %r: %s", agent_id, message),
            )

    return _resolve
