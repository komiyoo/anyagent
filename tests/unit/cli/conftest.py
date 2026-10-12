from __future__ import annotations

import sys
import types
from typing import Any

import pytest
from pydantic import BaseModel, Field

from anyagent.protocol.workspace import WorkspaceInitResult

_ISOLATED_ENV = (
    "PORT",
    "HOST",
    "API_KEY",
    "ADMIN_API_KEY",
    "AGENT_API_KEY",
    "STUDIO_DIR",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_VERSION",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "GEMINI_BASE_URL",
    "POSTGRES_DSN",
    "DATABASE_URL",
    "TOOL_RUNTIME_BASE_URL",
    "TOOL_RUNTIME_INTERNAL_KEY",
    "TOOL_RUNTIME_PLUGIN_ROOTS",
    "TOOL_RUNTIME_PLUGINS_FAIL_OPEN",
    "MANIFEST_CACHE_TTL_SECONDS",
    "STORAGE_MODE",
    "STORAGE_PROFILE",
    "WORKSPACE_DIR",
    "PLUGIN_ROOTS",
    "REPLAY_OBSERVABILITY_STDOUT",
    "LOG_FORMAT",
)


@pytest.fixture(autouse=True)
def isolate_config(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Keep CLI tests off the developer home config and process environment."""

    empty = tmp_path / "empty-config"
    empty.mkdir()
    monkeypatch.setenv("USER_CONFIG_DIR", str(empty))
    monkeypatch.setenv("SYSTEM_CONFIG_DIR", str(empty))
    for name in _ISOLATED_ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def scaffold(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Install the T4 scaffold contract without creating ``anyagent.scaffold``."""

    captured: dict[str, Any] = {}
    module = types.ModuleType("anyagent.scaffold")

    class InitOptions:
        def __init__(self, **kwargs: Any) -> None:
            self.__dict__.update(kwargs)

    class AddOptions:
        def __init__(self, **kwargs: Any) -> None:
            self.__dict__.update(kwargs)

    class ScaffoldResult(BaseModel):
        created: list[str] = Field(default_factory=list)
        skipped: list[str] = Field(default_factory=list)
        updated: list[str] = Field(default_factory=list)
        next_steps: list[str] = Field(default_factory=list)

    def init_workspace(options: InitOptions) -> WorkspaceInitResult:
        captured["init"] = options
        return WorkspaceInitResult(
            ok=True,
            workspace=str(options.workspace),
            agent_id=str(options.agent_id),
            created=[f".anyagent/agents/{options.agent_id}/agent.yaml"],
            skipped=[],
            next="anyagent doctor",
        )

    def add_component(options: AddOptions) -> ScaffoldResult:
        captured["add"] = options
        return ScaffoldResult(
            created=[f"{options.kind}/{options.name}"],
            next_steps=["wire the new component"],
        )

    def export_config_schemas() -> dict[str, dict[str, str]]:
        return {
            "anyagent.yaml": {"title": "anyagent"},
            "agent.yaml": {"title": "agent"},
            "mcp.json": {"title": "mcp"},
        }

    module.InitOptions = InitOptions
    module.AddOptions = AddOptions
    module.ScaffoldResult = ScaffoldResult
    module.init_workspace = init_workspace
    module.add_component = add_component
    module.export_config_schemas = export_config_schemas
    monkeypatch.setitem(sys.modules, "anyagent.scaffold", module)
    return captured
