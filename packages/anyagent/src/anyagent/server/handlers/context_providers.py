from __future__ import annotations

import contextlib
import logging
import sys
from pathlib import Path
from typing import Any

from anyagent.agent_packs import AgentPack
from anyagent.agent_runtime.context_providers import (
    ContextProvider,
    ContextProviderLoadError,
    ContextProviderRequest,
    collect_context_provider_fragments,
    load_context_provider_from_classpath,
)
from anyagent.protocol.context_fragments import ContextFragment
from anyagent.protocol.tool_runtime import ToolContext
from anyagent.skills.models import SkillPackage


_LOGGER = logging.getLogger(__name__)


@contextlib.contextmanager
def _workspace_import_paths(workspace_dir: Path):
    candidates = [workspace_dir, workspace_dir / "src"]
    added: list[str] = []
    for candidate in candidates:
        if not candidate.exists():
            continue
        value = str(candidate.resolve())
        if value in sys.path:
            continue
        sys.path.insert(0, value)
        added.append(value)
    try:
        yield
    finally:
        for value in added:
            with contextlib.suppress(ValueError):
                sys.path.remove(value)


def _load_context_providers_for_pack(*, pack: AgentPack, workspace_dir: Path) -> list[ContextProvider]:
    configured = [
        item.strip()
        for item in (pack.spec.runtime.context_providers or [])
        if isinstance(item, str) and item.strip()
    ]
    providers: list[ContextProvider] = []
    if not configured:
        return providers

    with _workspace_import_paths(workspace_dir):
        for classpath in configured:
            try:
                providers.append(load_context_provider_from_classpath(classpath))
            except ContextProviderLoadError as e:
                _LOGGER.warning("skipping context provider %r for agent %r: %s", classpath, pack.agent_id, e)
    return providers


async def _build_context_provider_fragments(
    *,
    pack: AgentPack,
    agent_id: str,
    session_key: str | None,
    body: dict[str, Any],
    metadata: dict[str, Any] | None,
    workspace_dir: Path,
    tool_context: ToolContext,
    selected_skills: list[SkillPackage],
) -> list[ContextFragment]:
    providers = _load_context_providers_for_pack(pack=pack, workspace_dir=workspace_dir)
    if not providers:
        return []

    request = ContextProviderRequest(
        agent_id=agent_id,
        session_key=session_key,
        body=body,
        metadata=metadata,
        workspace_dir=workspace_dir,
        pack=pack,
        tool_context=tool_context,
        selected_skills=selected_skills,
    )
    fragments: list[ContextFragment] = []
    with _workspace_import_paths(workspace_dir):
        for provider in providers:
            try:
                fragments.extend(await collect_context_provider_fragments([provider], request))
            except Exception as e:  # noqa: BLE001
                _LOGGER.warning(
                    "context provider failed for agent %r provider=%s: %s",
                    agent_id,
                    type(provider).__name__,
                    e,
                )
    return fragments
