from __future__ import annotations

from pathlib import Path

import pytest

from anyagent.cli import main


def test_agent_api_serve_builds_distributed_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: dict[str, object] = {}

    def fake_create_distributed_agent_app(**kwargs):
        calls["app_kwargs"] = kwargs
        return object()

    def fake_uvicorn_run(app, *, host, port, log_level):
        calls["uvicorn"] = {"app": app, "host": host, "port": port, "log_level": log_level}

    monkeypatch.setenv("TOOL_RUNTIME_INTERNAL_KEY", "env-internal-key")
    monkeypatch.setenv("TOOL_RUNTIME_BASE_URL", "http://tool-runtime.local")
    monkeypatch.setenv("MANIFEST_CACHE_TTL_SECONDS", "12.5")
    monkeypatch.setattr("anyagent.cli.services.create_distributed_agent_app", fake_create_distributed_agent_app)
    monkeypatch.setattr("anyagent.cli.services.uvicorn.run", fake_uvicorn_run)

    rc = main(
        [
            "agent-api",
            "serve",
            "--workspace",
            str(tmp_path),
            "--host",
            "0.0.0.0",
            "--port",
            "9999",
            "--api-key",
            "agent-key",
        ]
    )

    assert rc == 0
    app_kwargs = calls["app_kwargs"]
    assert isinstance(app_kwargs, dict)
    assert app_kwargs["api_key"] == "agent-key"
    assert app_kwargs["enable_keyed_serialization"] is True
    runtime_config = app_kwargs["runtime_config"]
    assert runtime_config.workspace_dir == str(tmp_path.resolve())
    assert runtime_config.tool_runtime_base_url == "http://tool-runtime.local"
    assert runtime_config.tool_runtime_internal_key == "env-internal-key"
    assert runtime_config.manifest_cache_ttl_seconds == 12.5
    uvicorn_call = calls["uvicorn"]
    assert isinstance(uvicorn_call, dict)
    assert uvicorn_call["host"] == "0.0.0.0"
    assert uvicorn_call["port"] == 9999


def test_tool_runtime_serve_uses_config_port(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: dict[str, object] = {}

    async def fake_create(*, config):
        calls["config"] = config
        return object()

    def fake_uvicorn_run(app, *, host, port, log_level):
        calls["uvicorn"] = {"app": app, "host": host, "port": port, "log_level": log_level}

    monkeypatch.setattr("anyagent.cli.services.create_tool_runtime_app_async", fake_create)
    monkeypatch.setattr("anyagent.cli.services.uvicorn.run", fake_uvicorn_run)

    rc = main(
        [
            "tool-runtime",
            "serve",
            "--workspace",
            str(tmp_path),
            "--host",
            "127.0.0.1",
            "--port",
            "8799",
            "--internal-key",
            "internal",
            "--admin-key",
            "admin",
        ]
    )

    assert rc == 0
    config = calls["config"]
    assert config.port == 8799  # type: ignore[attr-defined]
    assert config.host == "127.0.0.1"  # type: ignore[attr-defined]
    assert config.internal_key == "internal"  # type: ignore[attr-defined]
    assert config.admin_api_key == "admin"  # type: ignore[attr-defined]
    assert config.plugins_fail_open is False  # type: ignore[attr-defined]
    uvicorn_call = calls["uvicorn"]
    assert isinstance(uvicorn_call, dict)
    assert uvicorn_call["port"] == 8799
