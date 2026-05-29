from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

import jsonschema

from anyagent.agent_runtime.middleware import (
    AgentMiddleware,
    MiddlewareLoadError,
    load_middleware_from_classpath,
)

from .api import AnyAgentPluginAPI
from .hooks import PluginHookError, PluginHooks, load_plugin_hooks
from .models import PluginManifest


class PluginLoadError(Exception):
    pass


_ENTRYPOINT_RE = re.compile(r"^(?P<relpath>[^:]+):(?P<attr>[a-zA-Z_][a-zA-Z0-9_]*)$")


@dataclass(frozen=True)
class LoadedPlugin:
    manifest: PluginManifest
    plugin_dir: Path
    middlewares: list[AgentMiddleware] = field(default_factory=list)
    hooks: PluginHooks = field(default_factory=PluginHooks)
    declared_skills: list[str] = field(default_factory=list)
    declared_mcp_servers: list[str] = field(default_factory=list)
    declared_tools: list[str] = field(default_factory=list)


@contextlib.contextmanager
def _temporary_sys_path(path: Path) -> Iterator[None]:
    """Temporarily expose ``path`` on sys.path so plugin modules become importable."""

    resolved = str(Path(path).resolve())
    added = resolved not in sys.path
    if added:
        sys.path.insert(0, resolved)
    try:
        yield
    finally:
        if added:
            with contextlib.suppress(ValueError):
                sys.path.remove(resolved)


def _load_json_file(path: Path, *, max_bytes: int) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except FileNotFoundError as e:
        raise PluginLoadError(f"missing file: {path}") from e
    except Exception as e:  # noqa: BLE001
        raise PluginLoadError(f"failed to read file: {path}: {e}") from e

    if len(raw) > max_bytes:
        raise PluginLoadError(f"file too large: {path} (max {max_bytes} bytes)")

    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        raise PluginLoadError(f"invalid json: {path}: {e}") from e

    if not isinstance(data, dict):
        raise PluginLoadError(f"json must be an object: {path}")
    return data


def load_plugin_manifest(plugin_dir: Path) -> PluginManifest:
    plugin_dir = Path(plugin_dir)
    data = _load_json_file(plugin_dir / "plugin.json", max_bytes=256 * 1024)
    manifest = PluginManifest.model_validate(data)

    if manifest.config_schema is not None:
        try:
            jsonschema.Draft7Validator.check_schema(manifest.config_schema)
        except Exception as e:  # noqa: BLE001
            raise PluginLoadError(f"invalid config_schema in plugin.json: {e}") from e

    return manifest


def load_plugin_config(plugin_dir: Path, manifest: PluginManifest) -> dict[str, Any]:
    """
    v0 约定：插件目录下可选的 config.json（建议只存 env var 名称等非敏感配置）。
    若 manifest.config_schema 存在，则必须通过 jsonschema 校验。
    """
    plugin_dir = Path(plugin_dir)
    config_path = plugin_dir / "config.json"
    if not config_path.is_file():
        return {}

    data = _load_json_file(config_path, max_bytes=64 * 1024)

    if manifest.config_schema is not None:
        try:
            jsonschema.validate(instance=data, schema=manifest.config_schema)
        except jsonschema.ValidationError as e:
            raise PluginLoadError(f"config.json does not match config_schema: {e.message}") from e
        except Exception as e:  # noqa: BLE001
            raise PluginLoadError(f"failed to validate config.json: {e}") from e

    return data


def _parse_entrypoint(entrypoint: str) -> tuple[str, str]:
    m = _ENTRYPOINT_RE.match(entrypoint.strip())
    if not m:
        raise PluginLoadError("invalid entrypoint format (expected 'file.py:attr')")
    return m.group("relpath"), m.group("attr")


def _module_name_for(plugin_dir: Path, plugin_id: str) -> str:
    """
    避免 sys.modules 冲突：按 (plugin_id + abs path) 生成稳定 hash。
    """
    h = hashlib.sha1(str(plugin_dir.resolve()).encode("utf-8")).hexdigest()[:10]
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", plugin_id)[:32]
    return f"anyagent_plugin_{safe}_{h}"


def _load_register_callable(plugin_dir: Path, *, plugin_id: str, entrypoint: str) -> Callable[[AnyAgentPluginAPI], Any]:
    relpath, attr = _parse_entrypoint(entrypoint)
    if relpath.startswith(("/", "\\")) or ".." in Path(relpath).parts:
        raise PluginLoadError("entrypoint path must be relative and must not contain '..'")

    py_path = (Path(plugin_dir) / relpath).resolve()
    plugin_root = Path(plugin_dir).resolve()
    if not py_path.is_relative_to(plugin_root):
        raise PluginLoadError("entrypoint must resolve under plugin_dir")
    if py_path.suffix != ".py":
        raise PluginLoadError("entrypoint file must be a .py file")
    if not py_path.is_file():
        raise PluginLoadError(f"entrypoint file not found: {py_path}")

    module_name = _module_name_for(Path(plugin_dir), plugin_id)
    spec = importlib.util.spec_from_file_location(module_name, py_path)
    if spec is None or spec.loader is None:
        raise PluginLoadError(f"cannot load python module from: {py_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as e:  # noqa: BLE001
        raise PluginLoadError(f"failed to import entrypoint module: {py_path}: {e}") from e

    try:
        register = getattr(module, attr)
    except AttributeError as e:
        raise PluginLoadError(f"missing entrypoint attr '{attr}' in {py_path}") from e
    if not callable(register):
        raise PluginLoadError(f"entrypoint attr '{attr}' is not callable: {py_path}")
    return register


def _resolve_declared_capabilities(
    manifest: PluginManifest,
    plugin_dir: Path,
) -> tuple[list[AgentMiddleware], PluginHooks, list[str], list[str], list[str]]:
    """Resolve a v1 manifest's declarative capability fields.

    - middlewares / hooks: imported & instantiated (under plugin_dir on sys.path).
    - skills / mcp_servers / tools: validated as declarations + returned for
      traceability — no duplicate loading, since existing scan/registry sinks own them.

    Raises PluginLoadError on any failure so the caller can isolate this plugin.
    """

    from anyagent.tool_runtime.registry import TOOL_NAME_RE

    plugin_root = Path(plugin_dir).resolve()

    declared_skills: list[str] = []
    for rel in manifest.skills:
        skill_dir = (plugin_root / rel).resolve()
        if not skill_dir.is_relative_to(plugin_root):
            raise PluginLoadError(f"declared skill path escapes plugin_dir: {rel!r}")
        if not (skill_dir / "SKILL.md").is_file():
            raise PluginLoadError(f"declared skill missing SKILL.md: {rel!r}")
        declared_skills.append(rel)

    # mcp_servers already validated as MCPServerConfig by the manifest model.
    declared_mcp_servers = sorted(manifest.mcp_servers.keys())

    declared_tools: list[str] = []
    for name in manifest.tools:
        if not isinstance(name, str) or not TOOL_NAME_RE.match(name):
            raise PluginLoadError(f"invalid declared tool name: {name!r}")
        declared_tools.append(name)

    middlewares: list[AgentMiddleware] = []
    hooks = PluginHooks()
    with _temporary_sys_path(plugin_root):
        for classpath in manifest.middlewares:
            try:
                middlewares.append(load_middleware_from_classpath(classpath))
            except MiddlewareLoadError as e:
                raise PluginLoadError(f"middleware load failed: {e}") from e
        if manifest.hooks:
            try:
                hooks = load_plugin_hooks(manifest.hooks)
            except PluginHookError as e:
                raise PluginLoadError(f"hook load failed: {e}") from e

    return middlewares, hooks, declared_skills, declared_mcp_servers, declared_tools


def discover_plugin_dirs(root: Path) -> list[Path]:
    root = Path(root)
    if not root.exists():
        return []
    # 约定：root 下任意包含 plugin.json 的目录即视为一个插件目录
    return sorted({p.parent for p in root.rglob("plugin.json") if p.is_file()}, key=lambda p: str(p))


def load_plugins_from_roots(
    roots: list[Path],
    *,
    api_factory: Callable[[PluginManifest, Path, dict[str, Any]], AnyAgentPluginAPI],
) -> tuple[list[LoadedPlugin], list[tuple[str, str]]]:
    """
    返回 (loaded, errors)，errors 为 (plugin_dir, reason)。
    """
    loaded: list[LoadedPlugin] = []
    errors: list[tuple[str, str]] = []

    for root in roots:
        for d in discover_plugin_dirs(root):
            try:
                manifest = load_plugin_manifest(d)
                config = load_plugin_config(d, manifest)
                api = api_factory(manifest, d, config)
                entrypoint = manifest.entrypoint or "plugin.py:register"
                register = _load_register_callable(d, plugin_id=manifest.plugin_id, entrypoint=entrypoint)
                register(api)
                middlewares, hooks, declared_skills, declared_mcp_servers, declared_tools = (
                    _resolve_declared_capabilities(manifest, d)
                )
                loaded.append(
                    LoadedPlugin(
                        manifest=manifest,
                        plugin_dir=d,
                        middlewares=middlewares,
                        hooks=hooks,
                        declared_skills=declared_skills,
                        declared_mcp_servers=declared_mcp_servers,
                        declared_tools=declared_tools,
                    )
                )
            except PluginLoadError as e:
                errors.append((str(d), str(e)))
            except Exception as e:  # noqa: BLE001
                errors.append((str(d), f"unexpected error: {e}"))

    return loaded, errors
