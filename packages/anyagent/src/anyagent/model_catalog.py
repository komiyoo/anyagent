from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

# Workspace models.yaml kind vocabulary. Not an HTTP adapter; the loop maps
# these kinds to pydantic-ai model strings in anyagent.agent_runtime.loop.models.

ModelProviderKind = Literal["openai", "openai_chat", "anthropic", "gemini"]


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    kind: ModelProviderKind
    aliases: frozenset[str]
    default_api_key_envs: tuple[str, ...]
    default_base_url: str

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
            "openai_chat": "OPENAI_BASE_URL",
            "anthropic": "ANTHROPIC_BASE_URL",
            "gemini": "GEMINI_BASE_URL",
        }[self.kind]
        return os.getenv(env_name) or self.default_base_url


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
