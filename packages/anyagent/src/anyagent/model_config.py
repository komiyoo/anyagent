from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field

from anyagent.agent_packs import AgentPack
from anyagent.agent_runtime.model_providers import ModelProvider, get_default_model_provider
from anyagent.agent_runtime.model_providers.registry import ModelProviderKind, get_provider_spec, resolve_provider_kind


class ModelConfigError(Exception):
    pass


_ENV_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class WorkspaceModelProviderConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: ModelProviderKind = "openai"
    base_url: AnyHttpUrl | None = None
    base_url_env: str | None = None
    api_key_env: str | None = None
    anthropic_version: str | None = None
    anthropic_version_env: str | None = None


_EXTRA_PARAMS_BLOCKLIST = frozenset({
    "model", "messages", "tools", "tool_choice", "input", "instructions",
    "contents", "system", "systemInstruction",
})


class WorkspaceModelConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider: str
    model: str
    params: dict[str, Any] = Field(default_factory=dict)
    extra_params: dict[str, Any] = Field(default_factory=dict)


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
    provider_kind: ModelProviderKind = resolve_provider_kind(provider_name)
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


def apply_effective_model_to_body(
    *, body: dict[str, Any], selection: EffectiveModelSelection, workspace_config: WorkspaceModelsConfig | None = None
) -> None:
    if (not isinstance(body.get("model"), str) or not body.get("model", "").strip()) and selection.model:
        body["model"] = selection.model
    if workspace_config is not None:
        model_alias = _resolve_model_alias(selection, workspace_config)
        if model_alias and model_alias in workspace_config.models:
            entry = workspace_config.models[model_alias]
            params = entry.params
            if params:
                for key, value in params.items():
                    if key not in body:
                        body[key] = value
            extra = entry.extra_params
            if extra:
                filtered = {k: v for k, v in extra.items() if k not in _EXTRA_PARAMS_BLOCKLIST}
                if filtered:
                    existing = body.get("_extra_params")
                    if isinstance(existing, dict):
                        merged = {**filtered, **existing}
                    else:
                        merged = filtered
                    body["_extra_params"] = merged


def _resolve_model_alias(selection: EffectiveModelSelection, workspace_config: WorkspaceModelsConfig) -> str | None:
    for alias, entry in workspace_config.models.items():
        if _clean(entry.model) == selection.model:
            return alias
        if alias == selection.model:
            return alias
    return None


def model_provider_for_selection(selection: EffectiveModelSelection) -> ModelProvider:
    if not selection.uses_workspace_provider and selection.provider_kind == "openai":
        return get_default_model_provider()

    try:
        return get_provider_spec(selection.provider_kind).build_from_selection(selection)
    except RuntimeError as e:
        raise ModelConfigError(str(e)) from e


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
