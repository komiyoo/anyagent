from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from anyagent.config.agents import AgentPack
from anyagent.agent_runtime.classpath import load_instance_from_classpath
from anyagent.protocol.scripted_reply import ScriptedReply
from anyagent.protocol.tool_runtime import ToolContext
from anyagent.skills.models import SkillPackage

_LOGGER = logging.getLogger(__name__)

DEFAULT_SCRIPTED_REPLY_TIMEOUT_S = 2.0


@dataclass(frozen=True)
class ScriptedReplyRequest:
    """Trusted server-side request context passed to scripted reply providers.

    Same shape as ``ContextProviderRequest`` plus ``previous_transcript_items``:
    the session's fallback transcript before this turn, so providers can decide
    on turn position (first turn, previous turn already scripted, ...).
    """

    agent_id: str
    session_key: str | None
    body: dict[str, Any]
    metadata: dict[str, Any] | None
    workspace_dir: Path
    pack: AgentPack
    tool_context: ToolContext
    selected_skills: list[SkillPackage]
    previous_transcript_items: list[dict[str, Any]]

    @property
    def is_first_turn(self) -> bool:
        return not self.previous_transcript_items


@runtime_checkable
class ScriptedReplyProvider(Protocol):
    """Application extension point: answer a known input without calling the model.

    Return ``None`` to continue into the agent loop. Return a ``ScriptedReply``
    (or a dict with the same shape) to short-circuit the turn with that text.
    Text only: no tool calls, no handoff, no multi-turn.
    """

    async def resolve(self, request: ScriptedReplyRequest) -> ScriptedReply | dict[str, Any] | None: ...


class BaseScriptedReplyProvider:
    async def resolve(self, request: ScriptedReplyRequest) -> ScriptedReply | dict[str, Any] | None:
        _ = request
        return None


class ScriptedReplyLoadError(Exception):
    """Raised when a scripted reply provider cannot be loaded from a class path."""


@dataclass(frozen=True)
class ScriptedReplyMatch:
    reply: ScriptedReply
    provider_name: str


def load_scripted_reply_provider_from_classpath(
    classpath: str,
    *,
    kwargs: dict[str, Any] | None = None,
) -> ScriptedReplyProvider:
    """Import and instantiate a scripted reply provider from ``"module.path:ClassName"``.

    Consumes trusted deployer-controlled ``agent.yaml`` configuration only.
    """

    return load_instance_from_classpath(
        classpath,
        label="scripted reply provider",
        required_method="resolve",
        error_cls=ScriptedReplyLoadError,
        kwargs=kwargs,
    )


def _coerce_reply(result: Any) -> ScriptedReply | None:
    if result is None:
        return None
    if isinstance(result, ScriptedReply):
        return result
    if isinstance(result, dict):
        return ScriptedReply.model_validate(result)
    raise TypeError(f"scripted reply provider must return ScriptedReply | dict | None, got {type(result)!r}")


async def resolve_scripted_reply(
    providers: list[ScriptedReplyProvider],
    request: ScriptedReplyRequest,
    *,
    timeout_s: float = DEFAULT_SCRIPTED_REPLY_TIMEOUT_S,
    warn: Callable[[str], None] | None = None,
) -> ScriptedReplyMatch | None:
    """Run providers in order; first non-``None`` reply wins.

    Failure semantics: a provider that raises, times out or returns a malformed
    value is skipped with a warning. The turn always falls through to the loop.
    """

    _warn = warn or (lambda message: _LOGGER.warning("%s", message))
    for provider in providers:
        provider_name = type(provider).__name__
        try:
            result = provider.resolve(request)
            if isinstance(result, Awaitable):
                result = await asyncio.wait_for(result, timeout=timeout_s)
            reply = _coerce_reply(result)
        except asyncio.TimeoutError:
            _warn(f"scripted reply provider {provider_name} timed out after {timeout_s}s; continuing to loop")
            continue
        except Exception as e:  # noqa: BLE001
            _warn(f"scripted reply provider {provider_name} failed: {e}; continuing to loop")
            continue
        if reply is None:
            continue
        return ScriptedReplyMatch(reply=reply, provider_name=provider_name)
    return None
