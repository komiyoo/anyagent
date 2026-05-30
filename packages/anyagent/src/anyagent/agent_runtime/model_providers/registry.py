from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Literal

from ._capabilities import ANTHROPIC_CAPS, GEMINI_CAPS, OPENAI_FULL, ProviderCapabilities
from .anthropic_messages import AnthropicMessagesModelProviderSettings, get_default_anthropic_model_provider
from .base import ModelProvider
from .google_gemini import GoogleGeminiModelProviderSettings, get_default_gemini_model_provider
from .openai_responses import OpenAIResponsesModelProviderSettings, get_default_model_provider as get_default_openai_model_provider

if TYPE_CHECKING:
    from anyagent.model_config import EffectiveModelSelection


ModelProviderKind = Literal["openai", "anthropic", "gemini"]


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    kind: ModelProviderKind
    aliases: frozenset[str]
    default_api_key_envs: tuple[str, ...]
    default_base_url: str
    capabilities: ProviderCapabilities
    build_default: Callable[[], ModelProvider]
    build_from_selection: Callable[["EffectiveModelSelection"], ModelProvider]

    @property
    def default_api_key_env_label(self) -> str:
        return " or ".join(self.default_api_key_envs)

    def read_default_api_key(self) -> str | None:
        for env_name in self.default_api_key_envs:
            value = os.getenv(env_name)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def read_default_base_url(self) -> str:
        env_name = {
            "openai": "OPENAI_BASE_URL",
            "anthropic": "ANTHROPIC_BASE_URL",
            "gemini": "GEMINI_BASE_URL",
        }[self.kind]
        return os.getenv(env_name) or self.default_base_url


def _build_openai_from_selection(selection: "EffectiveModelSelection") -> ModelProvider:
    return get_default_openai_model_provider(
        OpenAIResponsesModelProviderSettings(
            OPENAI_API_KEY=_api_key_for_selection(selection),
            OPENAI_BASE_URL=_base_url_for_selection(selection),
        )
    )


def _build_anthropic_from_selection(selection: "EffectiveModelSelection") -> ModelProvider:
    anthropic_version = (
        _env_value(getattr(selection, "anthropic_version_env", None))
        or getattr(selection, "anthropic_version", None)
        or os.getenv("ANTHROPIC_VERSION")
        or "2023-06-01"
    )
    return get_default_anthropic_model_provider(
        AnthropicMessagesModelProviderSettings(
            ANTHROPIC_API_KEY=_api_key_for_selection(selection),
            ANTHROPIC_BASE_URL=_base_url_for_selection(selection),
            ANTHROPIC_VERSION=anthropic_version,
            ANYAGENT_ANTHROPIC_STATE_MAX=int(os.getenv("ANYAGENT_ANTHROPIC_STATE_MAX", "1024")),
        )
    )


def _build_gemini_from_selection(selection: "EffectiveModelSelection") -> ModelProvider:
    return get_default_gemini_model_provider(
        GoogleGeminiModelProviderSettings(
            GOOGLE_API_KEY=_api_key_for_selection(selection),
            GEMINI_BASE_URL=_base_url_for_selection(selection),
            ANYAGENT_GEMINI_STATE_MAX=int(os.getenv("ANYAGENT_GEMINI_STATE_MAX", "1024")),
        )
    )


PROVIDER_REGISTRY: dict[ModelProviderKind, ProviderSpec] = {
    "openai": ProviderSpec(
        kind="openai",
        aliases=frozenset({"openai", "openai_responses", "responses"}),
        default_api_key_envs=("OPENAI_API_KEY",),
        default_base_url="https://api.openai.com/v1",
        capabilities=OPENAI_FULL,
        build_default=get_default_openai_model_provider,
        build_from_selection=_build_openai_from_selection,
    ),
    "anthropic": ProviderSpec(
        kind="anthropic",
        aliases=frozenset({"anthropic", "claude"}),
        default_api_key_envs=("ANTHROPIC_API_KEY",),
        default_base_url="https://api.anthropic.com/v1",
        capabilities=ANTHROPIC_CAPS,
        build_default=get_default_anthropic_model_provider,
        build_from_selection=_build_anthropic_from_selection,
    ),
    "gemini": ProviderSpec(
        kind="gemini",
        aliases=frozenset({"gemini", "google", "google_gemini"}),
        default_api_key_envs=("GOOGLE_API_KEY", "GEMINI_API_KEY"),
        default_base_url="https://generativelanguage.googleapis.com/v1beta",
        capabilities=GEMINI_CAPS,
        build_default=get_default_gemini_model_provider,
        build_from_selection=_build_gemini_from_selection,
    ),
}


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


def _api_key_for_selection(selection: "EffectiveModelSelection") -> str:
    spec = get_provider_spec(getattr(selection, "provider_kind"))
    api_key = _env_value(getattr(selection, "api_key_env", None)) or spec.read_default_api_key()
    if api_key:
        return api_key
    source = getattr(selection, "api_key_env", None) or spec.default_api_key_env_label
    raise RuntimeError(f"missing API key for model provider {getattr(selection, 'provider_name')}: set {source}")


def _base_url_for_selection(selection: "EffectiveModelSelection") -> str:
    spec = get_provider_spec(getattr(selection, "provider_kind"))
    return (
        _env_value(getattr(selection, "base_url_env", None))
        or getattr(selection, "base_url", None)
        or spec.read_default_base_url()
    )


def _env_value(name: str | None) -> str | None:
    if not name:
        return None
    value = os.getenv(name)
    return value.strip() if isinstance(value, str) and value.strip() else None
