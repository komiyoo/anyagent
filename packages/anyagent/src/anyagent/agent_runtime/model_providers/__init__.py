from __future__ import annotations

from .base import (
    ModelProvider,
    ModelProviderError,
    ModelProviderInvalidRequestError,
    ModelProviderLiveResponseStream,
    ModelProviderTransportError,
    ModelProviderUpstreamError,
)
from .openai_responses import (
    OpenAIResponsesModelProvider,
    OpenAIResponsesModelProviderSettings,
    create_openai_responses_model_provider,
    get_default_model_provider as get_default_openai_model_provider,
)
from .registry import (
    PROVIDER_REGISTRY,
    ProviderSpec,
    get_provider_spec,
    is_registered_provider_name,
    resolve_provider_kind,
)

__all__ = [
    "ModelProvider",
    "ModelProviderLiveResponseStream",
    "ModelProviderError",
    "ModelProviderInvalidRequestError",
    "ModelProviderTransportError",
    "ModelProviderUpstreamError",
    "OpenAIResponsesModelProvider",
    "OpenAIResponsesModelProviderSettings",
    "create_openai_responses_model_provider",
    "PROVIDER_REGISTRY",
    "ProviderSpec",
    "get_provider_spec",
    "is_registered_provider_name",
    "resolve_provider_kind",
    "get_default_model_provider",
    "get_default_openai_model_provider",
]


def get_default_model_provider() -> ModelProvider:
    """Default OpenAI Responses provider. Tests patch this as the offline model seam.

    Anthropic / Gemini / Chat Completions are selected via anyagent.yaml provider kind and
    run through pydantic-ai, not in-repo HTTP translators.
    """

    return get_default_openai_model_provider()
