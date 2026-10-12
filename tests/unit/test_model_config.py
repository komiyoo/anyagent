from __future__ import annotations

from pathlib import Path

from anyagent.config.agents import AgentPack, AgentSpec
from anyagent.config.loader import load_effective_config
from anyagent.config.models import apply_effective_model_to_body, resolve_effective_model_selection
from anyagent.config.schema import ModelsConfig


def _pack(*, model_default: str | None = None, provider: str = "openai") -> AgentPack:
    payload = {
        "exposed": True,
        "tools": {"requested_tool_names": []},
    }
    model = {"provider": provider}
    if model_default is not None:
        model["default"] = model_default
    payload["model"] = model
    return AgentPack(
        agent_id="delivery-agent",
        root_dir=Path("/tmp/delivery-agent"),
        spec=AgentSpec.model_validate(payload),
        agents_md_path=Path("/tmp/delivery-agent/AGENTS.md"),
        agents_md_text="",
        agents_md_sha256="0" * 64,
    )


def test_workspace_model_alias_resolves_provider_and_real_model() -> None:
    cfg = ModelsConfig.model_validate(
        {
            "default": "delivery-fast",
            "providers": {
                "aliyun-openai": {
                    "kind": "openai",
                    "api_key": "dashscope-secret",
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                }
            },
            "aliases": {
                "delivery-fast": {"provider": "aliyun-openai", "model": "qwen-plus"},
            },
        }
    )

    selection = resolve_effective_model_selection(models=cfg, pack=_pack(model_default="delivery-fast"))

    assert selection.provider_name == "aliyun-openai"
    assert selection.provider_kind == "openai"
    assert selection.model == "qwen-plus"
    assert selection.api_key == "dashscope-secret"
    assert selection.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"

    body: dict[str, object] = {}
    apply_effective_model_to_body(body=body, selection=selection)
    assert body["model"] == "qwen-plus"


def test_request_model_is_not_overwritten_by_agent_default() -> None:
    selection = resolve_effective_model_selection(
        models=ModelsConfig(),
        pack=_pack(model_default="gpt-4o-mini"),
    )
    body: dict[str, object] = {"model": "gpt-4.1"}

    apply_effective_model_to_body(body=body, selection=selection)

    assert body["model"] == "gpt-4.1"


def test_load_effective_config_reads_workspace_anyagent_yaml(tmp_path: Path) -> None:
    (tmp_path / ".anyagent").mkdir()
    (tmp_path / ".anyagent" / "anyagent.yaml").write_text(
        "\n".join(
            [
                "models:",
                "  default: workspace-alias",
                "  aliases:",
                "    workspace-alias:",
                "      provider: openai",
                "      model: gpt-5.5",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "ignored.yaml").write_text("models:\n  default: root\n", encoding="utf-8")

    config = load_effective_config(tmp_path, environ={"SYSTEM_CONFIG_DIR": str(tmp_path / "missing-system"), "USER_CONFIG_DIR": str(tmp_path / "missing-user")})

    assert config.models.default == "workspace-alias"
    assert config.models.aliases["workspace-alias"].model == "gpt-5.5"


def test_load_effective_config_expands_model_placeholders(tmp_path: Path) -> None:
    (tmp_path / ".anyagent").mkdir()
    (tmp_path / ".anyagent" / "anyagent.yaml").write_text(
        "\n".join(
            [
                "models:",
                "  aliases:",
                "    root:",
                "      provider: openai",
                "      model: ${OPENAI_MODEL}",
            ]
        ),
        encoding="utf-8",
    )

    config = load_effective_config(
        tmp_path,
        environ={
            "OPENAI_MODEL": "gpt-5.5",
            "SYSTEM_CONFIG_DIR": str(tmp_path / "missing-system"),
            "USER_CONFIG_DIR": str(tmp_path / "missing-user"),
        },
    )

    assert config.models.aliases["root"].model == "gpt-5.5"
