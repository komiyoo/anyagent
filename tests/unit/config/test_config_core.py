from __future__ import annotations

from pathlib import Path

import pytest

from anyagent.config.agents import BUILTIN_MAIN_INSTRUCTIONS, AgentPackError, load_agent_catalog
from anyagent.config.env import interpolate_string, load_dotenv, parse_dotenv
from anyagent.config.loader import ConfigLoadError, load_effective_config
from anyagent.config.models import resolve_effective_model_selection
from anyagent.config.schema import ModelsConfig


def _isolated(tmp_path: Path) -> dict[str, str]:
    return {
        "SYSTEM_CONFIG_DIR": str(tmp_path / "missing-system"),
        "USER_CONFIG_DIR": str(tmp_path / "missing-user"),
    }


def _pack(model_default: str):
    from anyagent.config.agents import AgentPack, AgentSpec

    return AgentPack(
        agent_id="main",
        root_dir=Path("/tmp/main"),
        spec=AgentSpec.model_validate({"model": model_default}),
        agents_md_path=Path("/tmp/main/AGENTS.md"),
        agents_md_text="",
        agents_md_sha256="0" * 64,
    )


def test_parse_dotenv_quotes_export_and_inline_comments() -> None:
    parsed = parse_dotenv(
        "\n".join(
            [
                "# comment",
                "export QUOTED=\"hello # not comment\"",
                "SINGLE='a b # literal'",
                "PLAIN=value # comment",
                'ESCAPED="line\\nbreak"',
                "",
            ]
        )
    )

    assert parsed["QUOTED"] == "hello # not comment"
    assert parsed["SINGLE"] == "a b # literal"
    assert parsed["PLAIN"] == "value"
    assert parsed["ESCAPED"] == "line\nbreak"


def test_load_dotenv_local_overrides_file_but_not_process_env(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("PLAIN=from-file\nOTHER=from-file\n", encoding="utf-8")
    (tmp_path / ".env.local").write_text("OTHER=from-local\n", encoding="utf-8")
    environ = {"PLAIN": "kept"}

    applied = load_dotenv(tmp_path, environ=environ)

    assert environ["PLAIN"] == "kept"
    assert environ["OTHER"] == "from-local"
    assert applied == {"OTHER": "from-local"}


def test_interpolation_default_and_missing_var() -> None:
    assert interpolate_string("${MISSING}", {}) == ("", None)
    assert interpolate_string("${MISSING:-fallback}", {}) == ("fallback", None)
    assert interpolate_string("${SET:-fallback}", {"SET": "yes"}) == ("yes", "SET")
    assert interpolate_string("${EMPTY:-${NESTED}}", {"EMPTY": "", "NESTED": "nested"}) == ("nested", "NESTED")


def test_layer_precedence_and_source_tracking(tmp_path: Path) -> None:
    system = tmp_path / "system"
    user = tmp_path / "user"
    system.mkdir()
    user.mkdir()
    (system / "anyagent.yaml").write_text("server:\n  host: system-host\n", encoding="utf-8")
    (user / "anyagent.yaml").write_text("server:\n  host: user-host\n", encoding="utf-8")
    workspace = tmp_path / "workspace"
    (workspace / ".anyagent").mkdir(parents=True)
    (workspace / ".anyagent" / "anyagent.yaml").write_text(
        "server:\n  host: workspace-host\nmodels:\n  default: workspace-model\n",
        encoding="utf-8",
    )
    environ = {
        "SYSTEM_CONFIG_DIR": str(system),
        "USER_CONFIG_DIR": str(user),
        "API_KEY": "secret-key",
        "POSTGRES_DSN": "postgresql://user:secret@localhost:5432/db",
    }

    loaded = load_effective_config(workspace, cli_overrides={"server": {"port": 19090}}, environ=environ)

    assert loaded.server.host == "workspace-host"
    assert loaded.sources["server.host"].layer == "workspace"
    assert loaded.sources["server.host"].env is None
    assert loaded.server.port == 19090
    assert loaded.sources["server.port"].layer == "cli"
    assert loaded.models.default == "workspace-model"
    assert loaded.sources["models.default"].layer == "workspace"
    assert loaded.server.api_key == "secret-key"
    assert loaded.sources["server.api_key"].layer == "default"
    assert loaded.sources["server.api_key"].env == "API_KEY"
    assert loaded.storage.postgres_dsn == "postgresql://user:secret@localhost:5432/db"
    assert loaded.sources["storage.postgres_dsn"].env == "POSTGRES_DSN"


def test_redacted_dump_masks_keys_and_dsn_passwords(tmp_path: Path) -> None:
    loaded = load_effective_config(
        tmp_path,
        environ={
            **_isolated(tmp_path),
            "API_KEY": "secret-key",
            "POSTGRES_DSN": "postgresql://user:secret@localhost:5432/db",
        },
    )

    redacted = loaded.redacted_dump()

    assert redacted["server"]["api_key"] == "***"
    assert redacted["storage"]["postgres_dsn"] == "postgresql://user:***@localhost:5432/db"


def test_workspace_cannot_override_storage_set_by_system(tmp_path: Path) -> None:
    system = tmp_path / "system"
    system.mkdir()
    (system / "anyagent.yaml").write_text("storage:\n  profile: inmemory\n", encoding="utf-8")
    workspace = tmp_path / "workspace"
    (workspace / ".anyagent").mkdir(parents=True)
    (workspace / ".anyagent" / "anyagent.yaml").write_text("storage:\n  profile: postgres\n", encoding="utf-8")

    with pytest.raises(ConfigLoadError, match="workspace config cannot override sensitive field storage"):
        load_effective_config(
            workspace,
            environ={"SYSTEM_CONFIG_DIR": str(system), "USER_CONFIG_DIR": str(tmp_path / "missing-user")},
        )


def test_unknown_anyagent_yaml_key_names_the_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    config_path = workspace / ".anyagent" / "anyagent.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("models:\n  typo_field: 1\n", encoding="utf-8")

    with pytest.raises(ConfigLoadError, match="invalid anyagent.yaml") as exc:
        load_effective_config(workspace, environ=_isolated(tmp_path))

    message = str(exc.value)
    assert str(config_path) in message
    assert "models.typo_field" in message
    assert "Extra inputs are not permitted" in message


def test_env_only_deployment_reads_postgres_dsn_and_api_key(tmp_path: Path) -> None:
    loaded = load_effective_config(
        tmp_path,
        environ={
            **_isolated(tmp_path),
            "DATABASE_URL": "postgresql://dbuser:dbpass@db.internal:5432/app",
            "API_KEY": "from-env",
        },
    )

    assert not (tmp_path / ".anyagent" / "anyagent.yaml").exists()
    assert loaded.server.api_key == "from-env"
    assert loaded.storage.postgres_dsn == "postgresql://dbuser:dbpass@db.internal:5432/app"
    assert loaded.sources["storage.postgres_dsn"].env == "DATABASE_URL"


def test_zero_config_builtin_main_uses_workspace_agents_md(tmp_path: Path) -> None:
    empty = load_agent_catalog(workspace_dir=tmp_path / "empty")
    main = empty.get("main")
    assert main is not None
    assert main.builtin is True
    assert main.spec.exposed is True
    assert main.spec.tools.requested_tool_names == []
    assert main.agents_md_text == BUILTIN_MAIN_INSTRUCTIONS

    workspace = tmp_path / "with-instructions"
    workspace.mkdir()
    (workspace / "AGENTS.md").write_text("workspace rules\n", encoding="utf-8")
    catalog = load_agent_catalog(workspace_dir=workspace)
    pack = catalog.get("main")
    assert pack is not None
    assert pack.builtin is True
    assert pack.agents_md_text == "workspace rules\n"


def test_agent_directory_needs_only_agents_md(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    agent_dir = workspace / ".anyagent" / "agents" / "worker"
    agent_dir.mkdir(parents=True)
    (agent_dir / "AGENTS.md").write_text("worker\n", encoding="utf-8")

    catalog = load_agent_catalog(workspace_dir=workspace)
    pack = catalog.get("worker")
    assert pack is not None
    assert pack.builtin is False
    assert pack.spec.exposed is True
    assert pack.spec.tools.requested_tool_names == []
    assert pack.spec.model.default is None

    yaml_only = tmp_path / "yaml-only"
    broken = yaml_only / ".anyagent" / "agents" / "broken"
    broken.mkdir(parents=True)
    (broken / "agent.yaml").write_text("exposed: true\n", encoding="utf-8")
    with pytest.raises(AgentPackError, match="missing required file"):
        load_agent_catalog(workspace_dir=yaml_only)


def test_model_shorthand_selects_provider_and_model() -> None:
    selection = resolve_effective_model_selection(models=ModelsConfig(), pack=_pack("anthropic:claude-x"))

    assert selection.provider_name == "anthropic"
    assert selection.provider_kind == "anthropic"
    assert selection.model == "claude-x"
    assert selection.alias is None
