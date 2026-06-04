from __future__ import annotations

import importlib
import re
from collections.abc import Awaitable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from anyagent.agent_packs import AgentPack
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


_CONTEXT_PROVIDER_CLASSPATH_RE = re.compile(r"^(?P<module>[A-Za-z_][\w.]*):(?P<attr>[A-Za-z_]\w*)$")


def _is_context_provider_like(obj: Any) -> bool:
    return callable(getattr(obj, "build_context", None))


def load_context_provider_from_classpath(
    classpath: str,
    *,
    kwargs: dict[str, Any] | None = None,
) -> ContextProvider:
    """Import and instantiate a context provider from ``"module.path:ClassName"``.

    This consumes trusted deployer-controlled configuration from ``agent.yaml``.
    Never pass model output or other untrusted text into this loader.
    """

    if not isinstance(classpath, str):
        raise ContextProviderLoadError(f"context provider classpath must be a string, got {type(classpath)!r}")
    match = _CONTEXT_PROVIDER_CLASSPATH_RE.match(classpath.strip())
    if match is None:
        raise ContextProviderLoadError(
            f"invalid context provider classpath (expected 'module.path:ClassName'): {classpath!r}"
        )

    module_path = match.group("module")
    attr = match.group("attr")

    try:
        module = importlib.import_module(module_path)
    except Exception as e:  # noqa: BLE001
        raise ContextProviderLoadError(f"cannot import context provider module {module_path!r}: {e}") from e

    try:
        target = getattr(module, attr)
    except AttributeError as e:
        raise ContextProviderLoadError(f"context provider attr {attr!r} not found in module {module_path!r}") from e

    if not isinstance(target, type):
        raise ContextProviderLoadError(f"context provider target {classpath!r} is not a class")

    try:
        instance = target(**(kwargs or {}))
    except Exception as e:  # noqa: BLE001
        raise ContextProviderLoadError(f"failed to instantiate context provider {classpath!r}: {e}") from e

    if not _is_context_provider_like(instance):
        raise ContextProviderLoadError(
            f"context provider {classpath!r} does not implement build_context(request)"
        )
    return instance


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
