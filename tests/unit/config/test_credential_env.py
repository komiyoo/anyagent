from __future__ import annotations

from pathlib import Path

import pytest

from anyagent.config.loader import ConfigLoadError, load_effective_config


def test_legacy_mcp_credential_env_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_CREDENTIAL_STORE_BACKEND", "file-write")

    with pytest.raises(ConfigLoadError, match="credentials.writable: true"):
        load_effective_config(tmp_path)


def test_legacy_mcp_credential_file_root_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_CREDENTIAL_STORE_FILE_ROOT", ".anyagent/credentials")

    with pytest.raises(ConfigLoadError, match="CREDENTIAL_FILE_ROOT"):
        load_effective_config(tmp_path)


def test_credential_backend_write_suffix_fails_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREDENTIAL_BACKEND", "file-write")

    with pytest.raises(ConfigLoadError, match="credentials.writable: true"):
        load_effective_config(tmp_path)


def test_credential_backend_and_writable_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREDENTIAL_BACKEND", "file")
    monkeypatch.setenv("CREDENTIAL_WRITABLE", "true")
    monkeypatch.setenv("CREDENTIAL_FILE_ROOT", "vault")

    loaded = load_effective_config(tmp_path)

    assert loaded.credentials.backend == "file"
    assert loaded.credentials.writable is True
    assert loaded.credentials.file.root == "vault"


def test_chatwoot_defaults_interpolate_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATWOOT_URL", "https://chat.example")
    monkeypatch.setenv("CHATWOOT_STATUS_CHANGES", "false")
    monkeypatch.setenv("CHATWOOT_REPLY_PACING_MIN_S", "1.5")

    loaded = load_effective_config(tmp_path)

    assert loaded.plugins.builtin == []
    assert loaded.plugins.chatwoot.url == "https://chat.example"
    assert loaded.plugins.chatwoot.status_changes is False
    assert loaded.plugins.chatwoot.reply_pacing_min_s == 1.5
    assert loaded.plugins.chatwoot.access_token is None
