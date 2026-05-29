from __future__ import annotations

import importlib
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


class PluginHookError(Exception):
    """Raised when a plugin lifecycle hook cannot be loaded from a class path."""


_HOOK_CLASSPATH_RE = re.compile(r"^(?P<module>[A-Za-z_][\w.]*):(?P<attr>[A-Za-z_]\w*)$")

#: Allowed lifecycle hook names (mirrors PluginManifest.hooks keys).
HOOK_NAMES = ("on_agent_start", "on_agent_end")


@dataclass
class HookContext:
    """Minimal context passed to plugin lifecycle hooks.

    Carries stable correlation keys so a hook can locate the run it belongs to.
    Hooks are invoked at run boundaries; the actual call sites are wired in a
    follow-up (this module only defines the interface + loader).
    """

    agent_id: str
    session_key: str | None = None
    response_id: str | None = None
    metadata: dict[str, Any] | None = None


@runtime_checkable
class AgentLifecycleHook(Protocol):
    def __call__(self, context: HookContext) -> Awaitable[None] | None: ...


@dataclass
class PluginHooks:
    """Resolved lifecycle hook callables for a plugin (any may be None)."""

    on_agent_start: Callable[[HookContext], Any] | None = None
    on_agent_end: Callable[[HookContext], Any] | None = None

    def get(self, name: str) -> Callable[[HookContext], Any] | None:
        if name == "on_agent_start":
            return self.on_agent_start
        if name == "on_agent_end":
            return self.on_agent_end
        return None


def load_hook_from_classpath(classpath: str) -> Callable[[HookContext], Any]:
    """Import a plugin lifecycle hook callable from a ``"module.path:callable"`` string.

    This consumes a TRUSTED server-side configuration surface (plugin manifests
    are controlled by the deployer), NOT agent-controllable input. It performs a
    plain ``importlib.import_module`` and is unrelated to the sandbox boundary.
    """

    if not isinstance(classpath, str):
        raise PluginHookError(f"hook classpath must be a string, got {type(classpath)!r}")
    match = _HOOK_CLASSPATH_RE.match(classpath.strip())
    if match is None:
        raise PluginHookError(f"invalid hook classpath (expected 'module.path:callable'): {classpath!r}")
    module_path = match.group("module")
    attr = match.group("attr")

    try:
        module = importlib.import_module(module_path)
    except Exception as e:  # noqa: BLE001
        raise PluginHookError(f"cannot import hook module {module_path!r}: {e}") from e

    try:
        target = getattr(module, attr)
    except AttributeError as e:
        raise PluginHookError(f"hook attr {attr!r} not found in module {module_path!r}") from e

    if not callable(target):
        raise PluginHookError(f"hook target {classpath!r} is not callable")
    return target


def load_plugin_hooks(hooks: dict[str, str]) -> PluginHooks:
    """Resolve a manifest ``hooks`` mapping into callables. Raises on unknown name."""

    resolved = PluginHooks()
    for name, classpath in hooks.items():
        if name not in HOOK_NAMES:
            raise PluginHookError(f"unknown hook name: {name!r} (allowed: {list(HOOK_NAMES)})")
        callable_ = load_hook_from_classpath(classpath)
        setattr(resolved, name, callable_)
    return resolved
