from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from anyagent.plugins import (
    LoadedPlugin,
    PluginManifest,
    load_plugins_from_roots,
)
from anyagent.plugins.api import PluginAPIBase


def _api_factory(manifest: PluginManifest, plugin_dir: Path, config: dict[str, Any]) -> PluginAPIBase:
    return PluginAPIBase(host_kind="tool_runtime", plugin_id=manifest.plugin_id, config=config)


_PLUGIN_PY = """
from anyagent.agent_runtime.middleware import BaseMiddleware

class AuditMiddleware(BaseMiddleware):
    pass

async def on_start(context):
    return None

async def on_end(context):
    return None

def register(api):
    return None
"""


def _make_plugin_dir(
    root: Path,
    *,
    plugin_id: str,
    manifest_extra: dict[str, Any],
    plugin_py: str = _PLUGIN_PY,
    with_skill: bool = False,
) -> Path:
    plugin_dir = root / plugin_id
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.py").write_text(textwrap.dedent(plugin_py), encoding="utf-8")
    manifest = {"plugin_id": plugin_id, "entrypoint": "plugin.py:register", **manifest_extra}
    (plugin_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    if with_skill:
        skill_dir = plugin_dir / "skills" / "demo"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# demo skill\n", encoding="utf-8")
    return plugin_dir


@pytest.fixture(autouse=True)
def _isolate_plugin_module() -> Any:
    # Each plugin's plugin.py imports as top-level module name "plugin" via the
    # temporary sys.path; drop it between tests so imports re-resolve cleanly.
    yield
    sys.modules.pop("plugin", None)


def test_loads_v1_plugin_with_middleware_hooks_and_declarations(tmp_path: Path) -> None:
    _make_plugin_dir(
        tmp_path,
        plugin_id="full",
        with_skill=True,
        manifest_extra={
            "middlewares": ["plugin:AuditMiddleware"],
            "hooks": {"on_agent_start": "plugin:on_start", "on_agent_end": "plugin:on_end"},
            "skills": ["skills/demo"],
            "mcp_servers": {"fs": {"command": "uvx", "args": ["mcp-server-fs"]}},
            "tools": ["my_tool"],
        },
    )

    loaded, errors = load_plugins_from_roots([tmp_path], api_factory=_api_factory)

    assert errors == []
    assert len(loaded) == 1
    plugin = loaded[0]
    assert isinstance(plugin, LoadedPlugin)
    assert len(plugin.middlewares) == 1
    assert plugin.middlewares[0].__class__.__name__ == "AuditMiddleware"
    assert plugin.hooks.on_agent_start is not None
    assert plugin.hooks.on_agent_end is not None
    assert plugin.declared_skills == ["skills/demo"]
    assert plugin.declared_mcp_servers == ["fs"]
    assert plugin.declared_tools == ["my_tool"]


def test_v0_plugin_without_capabilities_loads_with_empty_fields(tmp_path: Path) -> None:
    _make_plugin_dir(tmp_path, plugin_id="legacy", manifest_extra={"channels": ["feishu"]})

    loaded, errors = load_plugins_from_roots([tmp_path], api_factory=_api_factory)

    assert errors == []
    assert len(loaded) == 1
    plugin = loaded[0]
    assert plugin.middlewares == []
    assert plugin.hooks.on_agent_start is None
    assert plugin.declared_skills == []


def test_bad_middleware_classpath_isolates_to_errors(tmp_path: Path) -> None:
    # A middleware pointing at a missing attribute fails to load; the plugin is
    # reported in errors and excluded from loaded, but other plugins survive.
    _make_plugin_dir(
        tmp_path,
        plugin_id="broken",
        manifest_extra={"middlewares": ["plugin:DoesNotExist"]},
    )
    _make_plugin_dir(
        tmp_path,
        plugin_id="healthy",
        manifest_extra={"middlewares": ["plugin:AuditMiddleware"]},
    )

    loaded, errors = load_plugins_from_roots([tmp_path], api_factory=_api_factory)

    loaded_ids = {p.manifest.plugin_id for p in loaded}
    assert "healthy" in loaded_ids
    assert "broken" not in loaded_ids
    assert any("broken" in d and "middleware load failed" in reason for d, reason in errors)


def test_declared_skill_missing_skill_md_isolates_to_errors(tmp_path: Path) -> None:
    plugin_dir = _make_plugin_dir(
        tmp_path,
        plugin_id="noskill",
        manifest_extra={"skills": ["skills/ghost"]},
    )
    # Create the directory but omit SKILL.md.
    (plugin_dir / "skills" / "ghost").mkdir(parents=True)

    loaded, errors = load_plugins_from_roots([tmp_path], api_factory=_api_factory)

    assert loaded == []
    assert any("noskill" in d and "SKILL.md" in reason for d, reason in errors)
