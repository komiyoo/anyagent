from __future__ import annotations

from pathlib import Path

from anyagent.server.app_builders import _resolve_plugin_roots


def test_resolve_plugin_roots_defaults_to_workspace_plugins(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ANYAGENT_PLUGIN_ROOTS", raising=False)
    plugins = tmp_path / "plugins"
    plugins.mkdir()

    roots = _resolve_plugin_roots(None, workspace=tmp_path)

    assert plugins.resolve() in roots


def test_resolve_plugin_roots_skips_missing_default_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ANYAGENT_PLUGIN_ROOTS", raising=False)

    roots = _resolve_plugin_roots(None, workspace=tmp_path)

    assert tmp_path / "plugins" not in roots
    assert (tmp_path / "plugins").resolve() not in roots


def test_resolve_plugin_roots_env_overrides_default(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "plugins").mkdir()
    extra = tmp_path / "extra-plugins"
    extra.mkdir()
    monkeypatch.setenv("ANYAGENT_PLUGIN_ROOTS", "extra-plugins")

    roots = _resolve_plugin_roots(None, workspace=tmp_path)

    assert extra.resolve() in roots
    assert (tmp_path / "plugins").resolve() not in roots


def test_resolve_plugin_roots_explicit_list_skips_default(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ANYAGENT_PLUGIN_ROOTS", raising=False)
    (tmp_path / "plugins").mkdir()
    custom = tmp_path / "custom"
    custom.mkdir()

    roots = _resolve_plugin_roots(["custom"], workspace=tmp_path)

    assert custom.resolve() in roots
    assert (tmp_path / "plugins").resolve() not in roots
