from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field

from anyagent.agent_packs import AgentPack
from anyagent.agent_runtime.model_providers import (
    AnthropicMessagesModelProviderSettings,
    GoogleGeminiModelProviderSettings,
    ModelProvider,
    OpenAIResponsesModelProviderSettings,
    get_default_model_provider,
    get_default_anthropic_model_provider,
    get_default_gemini_model_provider,
    get_default_openai_model_provider,
)


class ModelConfigError(Exception):
    pass


ModelProviderKind = Literal["openai", "anthropic", "gemini"]
_ENV_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class WorkspaceModelProviderConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: ModelProviderKind = "openai"
    base_url: AnyHttpUrl | None = None
    base_url_env: str | None = None
    api_key_env: str | None = None
    anthropic_version: str | None = None
    anthropic_version_env: str | None = None


class WorkspaceModelConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider: str
    model: str


class WorkspaceModelsConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    default_model: str | None = None
    providers: dict[str, WorkspaceModelProviderConfig] = Field(default_factory=dict)
    models: dict[str, WorkspaceModelConfig] = Field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EffectiveModelSelection:
    provider_name: str
    provider_kind: ModelProviderKind
    model: str | None
    api_key_env: str | None = None
    base_url: str | None = None
    base_url_env: str | None = None
    anthropic_version: str | None = None
    anthropic_version_env: str | None = None

    @property
    def uses_workspace_provider(self) -> bool:
        return any(
            value is not None
            for value in (
                self.api_key_env,
                self.base_url,
                self.base_url_env,
                self.anthropic_version,
                self.anthropic_version_env,
            )
        )


def workspace_models_config_path(workspace_dir: str | Path) -> Path:
    return Path(workspace_dir).expanduser().resolve() / "models.yaml"


def load_workspace_models_config(workspace_dir: str | Path) -> WorkspaceModelsConfig:
    path = workspace_models_config_path(workspace_dir)
    if not path.is_file():
        return WorkspaceModelsConfig()
    try:
        obj = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        raise ModelConfigError(f"invalid models config: {path}: {e}") from e
    if obj is None:
        obj = {}
    if not isinstance(obj, dict):
        raise ModelConfigError(f"models config must be an object: {path}")
    obj = _expand_env_placeholders(obj, os.environ)
    try:
        return WorkspaceModelsConfig.model_validate(obj)
    except Exception as e:  # noqa: BLE001
        raise ModelConfigError(f"invalid models config: {path}: {e}") from e


def resolve_effective_model_selection(
    *,
    workspace_config: WorkspaceModelsConfig,
    pack: AgentPack,
) -> EffectiveModelSelection:
    configured_default = _clean(pack.spec.model.default) or _clean(workspace_config.default_model)
    provider_name = _clean(pack.spec.model.provider)
    model_name: str | None = None

    if configured_default and configured_default in workspace_config.models:
        model_entry = workspace_config.models[configured_default]
        provider_name = _clean(model_entry.provider)
        model_name = _clean(model_entry.model)
    else:
        model_name = configured_default

    if not provider_name:
        provider_name = "openai"
    provider_cfg = workspace_config.providers.get(provider_name)
    provider_kind: ModelProviderKind = _provider_kind_from_name(provider_name)
    if provider_cfg is not None:
        provider_kind = provider_cfg.kind

    return EffectiveModelSelection(
        provider_name=provider_name,
        provider_kind=provider_kind,
        model=model_name,
        api_key_env=_clean(pack.spec.model.api_key_env) or _clean(provider_cfg.api_key_env if provider_cfg else None),
        base_url=_clean(str(provider_cfg.base_url)) if provider_cfg and provider_cfg.base_url is not None else None,
        base_url_env=_clean(pack.spec.model.base_url_env) or _clean(provider_cfg.base_url_env if provider_cfg else None),
        anthropic_version=_clean(provider_cfg.anthropic_version if provider_cfg else None),
        anthropic_version_env=_clean(provider_cfg.anthropic_version_env if provider_cfg else None),
    )


def apply_effective_model_to_body(*, body: dict[str, Any], selection: EffectiveModelSelection) -> None:
    if (not isinstance(body.get("model"), str) or not body.get("model", "").strip()) and selection.model:
        body["model"] = selection.model


def model_provider_for_selection(selection: EffectiveModelSelection) -> ModelProvider:
    if not selection.uses_workspace_provider and selection.provider_kind == "openai":
        return get_default_model_provider()

    api_key = _env_value(selection.api_key_env) or _default_api_key(selection.provider_kind)
    base_url = _env_value(selection.base_url_env) or selection.base_url or _default_base_url(selection.provider_kind)
    if not api_key:
        source = selection.api_key_env or _default_api_key_env(selection.provider_kind)
        raise ModelConfigError(f"missing API key for model provider {selection.provider_name}: set {source}")

    if selection.provider_kind == "openai":
        return get_default_openai_model_provider(
            OpenAIResponsesModelProviderSettings(
                OPENAI_API_KEY=api_key,
                OPENAI_BASE_URL=base_url,
            )
        )
    if selection.provider_kind == "anthropic":
        anthropic_version = (
            _env_value(selection.anthropic_version_env)
            or selection.anthropic_version
            or os.getenv("ANTHROPIC_VERSION")
            or "2023-06-01"
        )
        return get_default_anthropic_model_provider(
            AnthropicMessagesModelProviderSettings(
                ANTHROPIC_API_KEY=api_key,
                ANTHROPIC_BASE_URL=base_url,
                ANTHROPIC_VERSION=anthropic_version,
                ANYAGENT_ANTHROPIC_STATE_MAX=int(os.getenv("ANYAGENT_ANTHROPIC_STATE_MAX", "1024")),
            )
        )
    if selection.provider_kind == "gemini":
        return get_default_gemini_model_provider(
            GoogleGeminiModelProviderSettings(
                GOOGLE_API_KEY=api_key,
                GEMINI_BASE_URL=base_url,
                ANYAGENT_GEMINI_STATE_MAX=int(os.getenv("ANYAGENT_GEMINI_STATE_MAX", "1024")),
            )
        )
    raise ModelConfigError(f"unsupported model provider kind: {selection.provider_kind}")


def _provider_kind_from_name(provider_name: str) -> ModelProviderKind:
    value = provider_name.strip().lower()
    if value in {"anthropic", "claude"}:
        return "anthropic"
    if value in {"gemini", "google", "google_gemini"}:
        return "gemini"
    return "openai"


def _default_api_key_env(kind: ModelProviderKind) -> str:
    if kind == "anthropic":
        return "ANTHROPIC_API_KEY"
    if kind == "gemini":
        return "GOOGLE_API_KEY or GEMINI_API_KEY"
    return "OPENAI_API_KEY"


def _default_api_key(kind: ModelProviderKind) -> str | None:
    if kind == "anthropic":
        return os.getenv("ANTHROPIC_API_KEY")
    if kind == "gemini":
        return os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    return os.getenv("OPENAI_API_KEY")


def _default_base_url(kind: ModelProviderKind) -> str:
    if kind == "anthropic":
        return os.getenv("ANTHROPIC_BASE_URL") or "https://api.anthropic.com/v1"
    if kind == "gemini":
        return os.getenv("GEMINI_BASE_URL") or "https://generativelanguage.googleapis.com/v1beta"
    return os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1"


def _env_value(name: str | None) -> str | None:
    if not name:
        return None
    value = os.getenv(name)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _expand_env_placeholders(value: Any, environ: dict[str, str]) -> Any:
    if isinstance(value, str):
        return _ENV_VAR_RE.sub(lambda match: environ.get(match.group(1), ""), value)
    if isinstance(value, list):
        return [_expand_env_placeholders(item, environ) for item in value]
    if isinstance(value, dict):
        return {key: _expand_env_placeholders(item, environ) for key, item in value.items()}
    return value


def _clean(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None
