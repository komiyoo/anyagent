from __future__ import annotations

from anyagent.agent_runtime.model_providers.registry import PROVIDER_REGISTRY, get_provider_spec, resolve_provider_kind


def test_provider_registry_aliases_defaults_and_keys():
    assert set(PROVIDER_REGISTRY) == {"openai", "openai_chat", "anthropic", "gemini"}
    assert resolve_provider_kind("claude") == "anthropic"
    assert resolve_provider_kind("google_gemini") == "gemini"
    assert get_provider_spec("gemini").default_api_key_envs == ("GOOGLE_API_KEY", "GEMINI_API_KEY")
    assert get_provider_spec("anthropic").default_base_url == "https://api.anthropic.com/v1"
