"""Model provider registry and effective model selection.

Selection reads ``EffectiveConfig.models`` only. Provider credentials are the
already-interpolated ``api_key`` and ``base_url`` values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from anyagent.config.models_kinds import ModelProviderKind
from anyagent.config.schema import ModelAliasConfig, ModelsConfig


class ModelConfigError(Exception):
    pass


_EXTRA_PARAMS_BLOCKLIST = frozenset(
    {
        "model",
        "messages",
        "tools",
        "tool_choice",
        "input",
        "instructions",
        "contents",
        "system",
        "systemInstruction",
    }
)


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    kind: ModelProviderKind
    aliases: frozenset[str]
    default_api_key_envs: tuple[str, ...]
    default_base_url: str

    @property
    def default_api_key_env_label(self) -> str:
        return " or ".join(self.default_api_key_envs)


PROVIDER_REGISTRY: dict[ModelProviderKind, ProviderSpec] = {
    "openai": ProviderSpec(
        kind="openai",
        aliases=frozenset({"openai", "openai_responses", "responses"}),
        default_api_key_envs=("OPENAI_API_KEY",),
        default_base_url="https://api.openai.com/v1",
    ),
    "anthropic": ProviderSpec(
        kind="anthropic",
        aliases=frozenset({"anthropic", "claude"}),
        default_api_key_envs=("ANTHROPIC_API_KEY",),
        default_base_url="https://api.anthropic.com/v1",
    ),
    "gemini": ProviderSpec(
        kind="gemini",
        aliases=frozenset({"gemini", "google", "google_gemini"}),
        default_api_key_envs=("GOOGLE_API_KEY", "GEMINI_API_KEY"),
        default_base_url="https://generativelanguage.googleapis.com/v1beta",
    ),
    "openai_chat": ProviderSpec(
        kind="openai_chat",
        aliases=frozenset({"openai_chat", "openai_chat_completions", "chat_completions"}),
        default_api_key_envs=("OPENAI_API_KEY",),
        default_base_url="https://api.openai.com/v1",
    ),
}


@dataclass(frozen=True, slots=True)
class EffectiveModelSelection:
    provider_name: str
    provider_kind: ModelProviderKind
    model: str | None
    api_key: str | None = None
    base_url: str | None = None
    anthropic_version: str | None = None
    alias: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    extra_params: dict[str, Any] = field(default_factory=dict)

    @property
    def uses_workspace_provider(self) -> bool:
        """True when this selection carries a credential or a non-default base URL.

        Built-in defaults fill the conventional provider base URL. That value
        still leaves the OpenAI factory injection seam in place so tests and
        offline serves keep working until a key or custom URL is configured.
        """

        if _clean(self.api_key) or _clean(self.anthropic_version):
            return True
        url = _clean(self.base_url)
        if not url:
            return False
        spec = PROVIDER_REGISTRY.get(self.provider_kind)
        if spec is None:
            return True
        return url.rstrip("/") != spec.default_base_url.rstrip("/")


def resolve_provider_kind(name_or_alias: str) -> ModelProviderKind:
    value = name_or_alias.strip().lower()
    for kind, spec in PROVIDER_REGISTRY.items():
        if value == kind or value in spec.aliases:
            return kind
    return "openai"


def is_registered_provider_name(name_or_alias: str) -> bool:
    value = name_or_alias.strip().lower()
    return any(value == kind or value in spec.aliases for kind, spec in PROVIDER_REGISTRY.items())


def get_provider_spec(kind: str) -> ProviderSpec:
    return PROVIDER_REGISTRY[resolve_provider_kind(kind)]


def resolve_effective_model_selection(
    *,
    pack: Any,
    config: Any | None = None,
    models: ModelsConfig | None = None,
    request_model: str | None = None,
) -> EffectiveModelSelection:
    """Resolve an agent model string against the effective models section.

    Order: explicit request model, then the agent ``model`` value, then
    ``models.default``. An alias wins over ``provider:model``. A known
    provider prefix selects that provider. Anything else is a bare model
    name on the default provider ``openai``.
    """

    catalog = models if models is not None else _models_of(config)
    configured = _clean(request_model) or _clean(_agent_model_default(pack)) or _clean(catalog.default)
    alias_name: str | None = None
    entry: ModelAliasConfig | None = None
    provider_name = "openai"
    model_name = configured

    if configured and configured in catalog.aliases:
        alias_name = configured
        entry = catalog.aliases[configured]
        provider_name = _clean(entry.provider) or "openai"
        model_name = _clean(entry.model)
    elif configured and ":" in configured:
        provider_part, _, model_part = configured.partition(":")
        if _is_provider_token(provider_part, catalog):
            provider_name = provider_part.strip()
            model_name = _clean(model_part)
        else:
            model_name = configured

    provider_cfg = _lookup_provider(catalog, provider_name)
    provider_kind = provider_cfg.kind if provider_cfg is not None else resolve_provider_kind(provider_name)
    if provider_cfg is not None and provider_cfg.kind:
        provider_kind = provider_cfg.kind
    canonical_name = _canonical_provider_name(catalog, provider_name)
    return EffectiveModelSelection(
        provider_name=canonical_name,
        provider_kind=provider_kind,
        model=model_name,
        api_key=_clean(provider_cfg.api_key) if provider_cfg is not None else None,
        base_url=_clean(str(provider_cfg.base_url)) if provider_cfg is not None and provider_cfg.base_url else None,
        anthropic_version=_clean(provider_cfg.anthropic_version) if provider_cfg is not None else None,
        alias=alias_name,
        params=dict(entry.params) if entry is not None else {},
        extra_params=dict(entry.extra_params) if entry is not None else {},
    )


def apply_effective_model_to_body(
    *,
    body: dict[str, Any],
    selection: EffectiveModelSelection,
    workspace_config: Any | None = None,
) -> None:
    """Fill an empty request model and merge alias params without overwriting caller keys."""

    _ = workspace_config
    if (not isinstance(body.get("model"), str) or not str(body.get("model") or "").strip()) and selection.model:
        body["model"] = selection.model
    for key, value in selection.params.items():
        if key not in body:
            body[key] = value
    filtered = {key: value for key, value in selection.extra_params.items() if key not in _EXTRA_PARAMS_BLOCKLIST}
    if not filtered:
        return
    existing = body.get("_extra_params")
    if isinstance(existing, dict):
        body["_extra_params"] = {**filtered, **existing}
    else:
        body["_extra_params"] = filtered


def _models_of(config: Any) -> ModelsConfig:
    if isinstance(config, ModelsConfig):
        return config
    models = getattr(config, "models", None)
    if isinstance(models, ModelsConfig):
        return models
    raise ModelConfigError("model selection requires an effective models configuration")


def _agent_model_default(pack: Any) -> str | None:
    spec = getattr(pack, "spec", None)
    model = getattr(spec, "model", None)
    default = getattr(model, "default", None)
    return default if isinstance(default, str) else None


def _lookup_provider(catalog: ModelsConfig, name: str):
    if name in catalog.providers:
        return catalog.providers[name]
    wanted = name.strip().lower()
    for key, provider in catalog.providers.items():
        if key.lower() == wanted or provider.kind == wanted:
            return provider
        if is_registered_provider_name(wanted) and provider.kind == resolve_provider_kind(wanted):
            if wanted == provider.kind or wanted in PROVIDER_REGISTRY[provider.kind].aliases or key.lower() == wanted:
                return provider
    kind = resolve_provider_kind(wanted) if is_registered_provider_name(wanted) else None
    if kind is not None:
        for provider in catalog.providers.values():
            if provider.kind == kind and (wanted == kind or wanted in PROVIDER_REGISTRY[kind].aliases):
                return provider
    return None


def _canonical_provider_name(catalog: ModelsConfig, name: str) -> str:
    if name in catalog.providers:
        return name
    provider = _lookup_provider(catalog, name)
    if provider is None:
        return name
    for key, candidate in catalog.providers.items():
        if candidate is provider:
            return key
    return name


def _is_provider_token(name: str, catalog: ModelsConfig) -> bool:
    token = name.strip()
    if not token:
        return False
    if token in catalog.providers:
        return True
    return is_registered_provider_name(token) or _lookup_provider(catalog, token) is not None


def _clean(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None
