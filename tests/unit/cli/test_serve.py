from __future__ import annotations

import json
from pathlib import Path

import pytest

from anyagent.cli import main
from anyagent.cli.serve import studio_bundle_dir


def _patch_serve(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    calls: dict[str, object] = {}

    def fake_create_app(**kwargs):
        calls["app_kwargs"] = kwargs
        return object()

    def fake_uvicorn_run(app, *, host, port, log_level):
        calls["uvicorn"] = {"app": app, "host": host, "port": port, "log_level": log_level}

    monkeypatch.setattr("anyagent.cli.serve.create_app", fake_create_app)
    monkeypatch.setattr("anyagent.cli.serve.uvicorn.run", fake_uvicorn_run)
    return calls


def test_dev_fills_empty_local_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    calls = _patch_serve(monkeypatch)

    rc = main(["dev", "--workspace", str(tmp_path), "--storage-profile", "postgres"])

    assert rc == 0
    app_kwargs = calls["app_kwargs"]
    assert isinstance(app_kwargs, dict)
    config = app_kwargs["config"]
    assert app_kwargs["workspace_dir"] == str(tmp_path.resolve())
    assert config.server.api_key == "anyagent-dev-key"
    assert config.server.admin_api_key == "anyagent-dev-key"
    assert config.server.studio_dir == str(studio_bundle_dir())
    assert studio_bundle_dir().parts[-3:] == ("anyagent", "studio", "dist")
    assert config.server.enable_studio is True
    assert config.storage.profile == "postgres"
    assert config.server.host == "127.0.0.1"
    assert config.server.port == 8787
    uvicorn_call = calls["uvicorn"]
    assert isinstance(uvicorn_call, dict)
    assert uvicorn_call["host"] == "127.0.0.1"
    assert uvicorn_call["port"] == 8787
    banner = json.loads(capsys.readouterr().out)
    assert banner["api"] == "http://127.0.0.1:8787/v1"
    assert banner["studio"] == "http://127.0.0.1:8787/studio/"
    assert banner["agents_exposed"] == ["main"]
    assert "storage" not in banner


def test_dev_keeps_configured_api_key_and_fills_admin_from_it(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("API_KEY", "from-env")
    calls = _patch_serve(monkeypatch)

    rc = main(["dev", "--workspace", str(tmp_path), "--quiet"])

    assert rc == 0
    config = calls["app_kwargs"]["config"]  # type: ignore[index]
    assert config.server.api_key == "from-env"
    assert config.server.admin_api_key == "from-env"
    assert capsys.readouterr().out == ""


def test_dev_no_studio_leaves_studio_disabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    calls = _patch_serve(monkeypatch)

    rc = main(["dev", "--workspace", str(tmp_path), "--no-studio"])

    assert rc == 0
    config = calls["app_kwargs"]["config"]  # type: ignore[index]
    assert config.server.enable_studio is False
    assert not config.server.studio_dir
    banner = json.loads(capsys.readouterr().out)
    assert banner["studio"] == "disabled"


def test_serve_lets_port_env_flow_through_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PORT", "9191")
    calls = _patch_serve(monkeypatch)

    rc = main(["serve", "--workspace", str(tmp_path), "--quiet"])

    assert rc == 0
    config = calls["app_kwargs"]["config"]  # type: ignore[index]
    assert config.server.api_key is None
    assert config.server.admin_api_key is None
    assert config.server.port == 9191
    assert config.sources["server.port"].layer == "default"
    assert config.sources["server.port"].env == "PORT"
    uvicorn_call = calls["uvicorn"]
    assert isinstance(uvicorn_call, dict)
    assert uvicorn_call["port"] == 9191


def test_serve_refuses_non_loopback_without_api_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = _patch_serve(monkeypatch)

    with pytest.raises(SystemExit, match="server.api_key"):
        main(["serve", "--workspace", str(tmp_path), "--host", "0.0.0.0", "--quiet"])

    assert "uvicorn" not in calls


def test_dev_on_non_loopback_keeps_dev_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = _patch_serve(monkeypatch)

    rc = main(["dev", "--workspace", str(tmp_path), "--host", "0.0.0.0", "--quiet"])

    assert rc == 0
    config = calls["app_kwargs"]["config"]  # type: ignore[index]
    assert config.server.host == "0.0.0.0"
    assert config.server.api_key == "anyagent-dev-key"


def test_serve_allows_non_loopback_when_api_key_is_set(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = _patch_serve(monkeypatch)

    rc = main(["serve", "--workspace", str(tmp_path), "--host", "0.0.0.0", "--api-key", "public-key", "--quiet"])

    assert rc == 0
    config = calls["app_kwargs"]["config"]  # type: ignore[index]
    assert config.server.api_key == "public-key"
    uvicorn_call = calls["uvicorn"]
    assert isinstance(uvicorn_call, dict)
    assert uvicorn_call["host"] == "0.0.0.0"


def test_serve_port_flag_is_a_cli_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PORT", "9191")
    monkeypatch.setenv("API_KEY", "serve-key")
    calls = _patch_serve(monkeypatch)

    rc = main(["serve", "--workspace", str(tmp_path), "--port", "9001", "--quiet"])

    assert rc == 0
    config = calls["app_kwargs"]["config"]  # type: ignore[index]
    assert config.server.api_key == "serve-key"
    assert config.server.admin_api_key is None
    assert config.server.port == 9001
    assert config.sources["server.port"].layer == "cli"
    assert config.sources["server.port"].env is None
