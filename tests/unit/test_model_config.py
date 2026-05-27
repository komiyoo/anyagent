from __future__ import annotations

from pathlib import Path

from anyagent.agent_packs import AgentPack, AgentSpec
from anyagent.model_config import (
    WorkspaceModelsConfig,
    apply_effective_model_to_body,
    load_workspace_models_config,
    resolve_effective_model_selection,
)


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
    cfg = WorkspaceModelsConfig.model_validate(
        {
            "default_model": "default",
            "providers": {
                "aliyun-openai": {
                    "kind": "openai",
                    "api_key_env": "DASHSCOPE_API_KEY",
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                }
            },
            "models": {
                "delivery-fast": {"provider": "aliyun-openai", "model": "qwen-plus"},
            },
        }
    )

    selection = resolve_effective_model_selection(workspace_config=cfg, pack=_pack(model_default="delivery-fast"))

    assert selection.provider_name == "aliyun-openai"
    assert selection.provider_kind == "openai"
    assert selection.model == "qwen-plus"
    assert selection.api_key_env == "DASHSCOPE_API_KEY"
    assert selection.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"

    body: dict[str, object] = {}
    apply_effective_model_to_body(body=body, selection=selection)
    assert body["model"] == "qwen-plus"


def test_request_model_is_not_overwritten_by_agent_default() -> None:
    selection = resolve_effective_model_selection(
        workspace_config=WorkspaceModelsConfig(),
        pack=_pack(model_default="gpt-4o-mini"),
    )
    body: dict[str, object] = {"model": "gpt-4.1"}

    apply_effective_model_to_body(body=body, selection=selection)

    assert body["model"] == "gpt-4.1"


def test_load_workspace_models_config_reads_only_workspace_root(tmp_path: Path) -> None:
    (tmp_path / ".anyagent").mkdir()
    (tmp_path / ".anyagent" / "models.yaml").write_text(
        "default_model: old\nmodels:\n  old:\n    provider: openai\n    model: gpt-4o-mini\n",
        encoding="utf-8",
    )
    (tmp_path / "models.yaml").write_text(
        "default_model: root\nmodels:\n  root:\n    provider: openai\n    model: gpt-5.5\n",
        encoding="utf-8",
    )

    config = load_workspace_models_config(tmp_path)

    assert config.default_model == "root"
    assert set(config.models) == {"root"}


def test_load_workspace_models_config_expands_env_placeholders(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.5")
    (tmp_path / "models.yaml").write_text(
        "default_model: root\nmodels:\n  root:\n    provider: openai\n    model: ${OPENAI_MODEL}\n",
        encoding="utf-8",
    )

    config = load_workspace_models_config(tmp_path)

    assert config.models["root"].model == "gpt-5.5"
