from __future__ import annotations

from anyagent.tool_runtime.cli_env import build_cli_env
from anyagent.tool_runtime.cli_profile_spec import CliEnvironmentPolicy


def test_build_cli_env_applies_inherit_filter_exclude_set_and_include_only(monkeypatch) -> None:
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("HOME", "/tmp/home")
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    monkeypatch.setenv("VISIBLE", "keep-me")
    monkeypatch.setenv("API_TOKEN", "redact-me")

    env = build_cli_env(
        CliEnvironmentPolicy(
            inherit="all",
            exclude=["HOME"],
            set={"VISIBLE": "overridden", "EXTRA": "value"},
            include_only=["PATH", "VISIBLE", "EXTRA", "API_TOKEN"],
        )
    )

    assert env == {
        "PATH": "/usr/bin",
        "VISIBLE": "overridden",
        "EXTRA": "value",
    }


def test_build_cli_env_core_inherit_keeps_only_core_keys(monkeypatch) -> None:
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("HOME", "/tmp/home")
    monkeypatch.setenv("CUSTOM_NAME", "drop-me")

    env = build_cli_env(CliEnvironmentPolicy(inherit="core"))

    assert env["PATH"] == "/usr/bin"
    assert env["HOME"] == "/tmp/home"
    assert "CUSTOM_NAME" not in env


def test_build_cli_env_can_disable_default_sensitive_filter(monkeypatch) -> None:
    monkeypatch.setenv("API_TOKEN", "keep-me")

    env = build_cli_env(
        CliEnvironmentPolicy(
            inherit="all",
            ignore_default_excludes=True,
            include_only=["API_TOKEN"],
        )
    )

    assert env == {"API_TOKEN": "keep-me"}
