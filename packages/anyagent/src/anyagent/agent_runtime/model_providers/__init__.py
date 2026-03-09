from __future__ import annotations

import os

from .base import (
    BufferedLiveResponseStream,
    ModelProvider,
    ModelProviderError,
    ModelProviderInvalidRequestError,
    ModelProviderLiveResponseStream,
    ModelProviderTransportError,
    ModelProviderUpstreamError,
)
from .anthropic_messages import (
    AnthropicMessagesModelProvider,
    AnthropicMessagesModelProviderSettings,
    create_anthropic_messages_model_provider,
    get_default_anthropic_model_provider,
)
from .google_gemini import (
    GoogleGeminiModelProvider,
    GoogleGeminiModelProviderSettings,
    create_google_gemini_model_provider,
    get_default_gemini_model_provider,
)
from .openai_responses import (
    OpenAIResponsesModelProvider,
    OpenAIResponsesModelProviderSettings,
    create_openai_responses_model_provider,
    get_default_model_provider as get_default_openai_model_provider,
)

__all__ = [
    "ModelProvider",
    "ModelProviderLiveResponseStream",
    "BufferedLiveResponseStream",
    "ModelProviderError",
    "ModelProviderInvalidRequestError",
    "ModelProviderTransportError",
    "ModelProviderUpstreamError",
    "AnthropicMessagesModelProvider",
    "AnthropicMessagesModelProviderSettings",
    "create_anthropic_messages_model_provider",
    "get_default_anthropic_model_provider",
    "GoogleGeminiModelProvider",
    "GoogleGeminiModelProviderSettings",
    "create_google_gemini_model_provider",
    "get_default_gemini_model_provider",
    "OpenAIResponsesModelProvider",
    "OpenAIResponsesModelProviderSettings",
    "create_openai_responses_model_provider",
    "get_default_model_provider",
    "get_default_openai_model_provider",
]


def get_default_model_provider() -> ModelProvider:
    """
    Returns a singleton-ish default ModelProvider based on environment variables.

    Env:
    - ANYAGENT_MODEL_PROVIDER: "openai" (default) | "anthropic" | "gemini"
    """

    kind = (os.getenv("ANYAGENT_MODEL_PROVIDER") or "openai").strip().lower()
    if kind in {"openai", "openai_responses", "responses"}:
        return get_default_openai_model_provider()
    if kind in {"anthropic", "claude"}:
        return get_default_anthropic_model_provider()
    if kind in {"gemini", "google", "google_gemini"}:
        return get_default_gemini_model_provider()
    raise ValueError(f"unsupported ANYAGENT_MODEL_PROVIDER: {kind}")
