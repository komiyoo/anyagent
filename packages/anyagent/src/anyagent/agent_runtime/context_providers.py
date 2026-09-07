from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from anyagent.agent_packs import AgentPack
from anyagent.agent_runtime.classpath import load_instance_from_classpath
from anyagent.protocol.context_fragments import ContextFragment
from anyagent.protocol.tool_runtime import ToolContext
from anyagent.skills.models import SkillPackage


@dataclass(frozen=True)
class ContextProviderRequest:
    """Trusted server-side request context passed to business context providers."""

    agent_id: str
    session_key: str | None
    body: dict[str, Any]
    metadata: dict[str, Any] | None
    workspace_dir: Path
    pack: AgentPack
    tool_context: ToolContext
    selected_skills: list[SkillPackage]


@runtime_checkable
class ContextProvider(Protocol):
    """Application extension point for adding model-visible prompt context."""

    async def build_context(self, request: ContextProviderRequest) -> list[ContextFragment]: ...


class BaseContextProvider:
    async def build_context(self, request: ContextProviderRequest) -> list[ContextFragment]:
        _ = request
        return []


class ContextProviderLoadError(Exception):
    """Raised when a context provider cannot be loaded from a class path."""


def load_context_provider_from_classpath(
    classpath: str,
    *,
    kwargs: dict[str, Any] | None = None,
) -> ContextProvider:
    """Import and instantiate a context provider from ``"module.path:ClassName"``.

    This consumes trusted deployer-controlled configuration from ``agent.yaml``.
    Never pass model output or other untrusted text into this loader.
    """

    return load_instance_from_classpath(
        classpath,
        label="context provider",
        required_method="build_context",
        error_cls=ContextProviderLoadError,
        kwargs=kwargs,
    )


async def collect_context_provider_fragments(
    providers: list[ContextProvider],
    request: ContextProviderRequest,
) -> list[ContextFragment]:
    fragments: list[ContextFragment] = []
    for provider in providers:
        result = provider.build_context(request)
        if isinstance(result, Awaitable):
            result = await result
        if not isinstance(result, list):
            continue
        for item in result:
            if isinstance(item, ContextFragment):
                fragments.append(item)
            elif isinstance(item, dict):
                try:
                    fragments.append(ContextFragment.model_validate(item))
                except Exception:  # noqa: BLE001
                    continue
    return fragments
