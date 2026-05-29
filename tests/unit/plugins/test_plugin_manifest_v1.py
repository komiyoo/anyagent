from __future__ import annotations

import pytest
from pydantic import ValidationError

from anyagent.plugins import PluginManifest


def test_manifest_v0_still_parses_without_v1_fields() -> None:
    manifest = PluginManifest.model_validate(
        {
            "id": "legacy",
            "channels": ["feishu"],
            "entrypoint": "plugin.py:register",
            "some_unknown_future_field": {"ignored": True},
        }
    )

    assert manifest.plugin_id == "legacy"
    assert manifest.channels == ["feishu"]
    assert manifest.skills == []
    assert manifest.mcp_servers == {}
    assert manifest.tools == []
    assert manifest.middlewares == []
    assert manifest.hooks == {}


def test_manifest_v1_parses_all_five_capability_fields() -> None:
    manifest = PluginManifest.model_validate(
        {
            "plugin_id": "full",
            "skills": ["skills/my-skill"],
            "mcp_servers": {"fs": {"command": "uvx", "args": ["mcp-server-fs"]}},
            "tools": ["my_tool", "another_tool"],
            "middlewares": ["my_plugin.mw:AuditMiddleware"],
            "hooks": {"on_agent_start": "my_plugin.hooks:on_start"},
        }
    )

    assert manifest.skills == ["skills/my-skill"]
    assert "fs" in manifest.mcp_servers
    assert manifest.mcp_servers["fs"].command == "uvx"
    assert manifest.tools == ["my_tool", "another_tool"]
    assert manifest.middlewares == ["my_plugin.mw:AuditMiddleware"]
    assert manifest.hooks == {"on_agent_start": "my_plugin.hooks:on_start"}


def test_manifest_strips_whitespace_in_classpaths() -> None:
    manifest = PluginManifest.model_validate(
        {
            "plugin_id": "ws",
            "middlewares": ["  my_plugin.mw:Mw  "],
            "hooks": {"on_agent_end": "  my_plugin.hooks:on_end  "},
        }
    )
    assert manifest.middlewares == ["my_plugin.mw:Mw"]
    assert manifest.hooks == {"on_agent_end": "my_plugin.hooks:on_end"}


@pytest.mark.parametrize(
    "bad",
    [
        "NoColon",
        ":MissingModule",
        "module.path:",
        "module.path:Class:Extra",
        "1bad.module:Class",
        "module.path:1Class",
        "module path:Class",
    ],
)
def test_manifest_rejects_malformed_middleware_classpath(bad: str) -> None:
    with pytest.raises(ValidationError):
        PluginManifest.model_validate({"plugin_id": "x", "middlewares": [bad]})


def test_manifest_rejects_unknown_hook_name() -> None:
    with pytest.raises(ValidationError):
        PluginManifest.model_validate(
            {"plugin_id": "x", "hooks": {"on_tool_call": "my_plugin.hooks:cb"}}
        )


def test_manifest_rejects_malformed_hook_classpath() -> None:
    with pytest.raises(ValidationError):
        PluginManifest.model_validate(
            {"plugin_id": "x", "hooks": {"on_agent_start": "not-a-classpath"}}
        )
