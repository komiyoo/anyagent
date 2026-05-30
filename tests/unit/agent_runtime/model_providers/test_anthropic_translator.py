from __future__ import annotations

import json
from pathlib import Path

from anyagent.agent_runtime.model_providers._translation import ToolNameMapping
from anyagent.agent_runtime.model_providers.anthropic_messages import (
    AnthropicMessagesModelProviderSettings,
    AnthropicTranslator,
)


def _settings() -> AnthropicMessagesModelProviderSettings:
    return AnthropicMessagesModelProviderSettings(
        ANTHROPIC_API_KEY="test-key",
        ANTHROPIC_BASE_URL="https://example.test/v1",
    )


def _fixture(name: str) -> dict:
    path = Path(__file__).parents[3] / "fixtures" / "model_providers" / "anthropic" / name
    return json.loads(path.read_text(encoding="utf-8"))


def test_anthropic_required_tool_choice_maps_to_any_and_developer_system_is_read():
    names = ToolNameMapping(
        model_to_source={"core_lookup": "core.lookup"},
        source_to_model={"core.lookup": "core_lookup"},
    )
    req = AnthropicTranslator().build_request(
        body={
            "model": "claude-test",
            "instructions": "base",
            "input": [{"role": "developer", "content": "dev"}, {"role": "user", "content": "hi"}],
            "tools": [{"type": "function", "name": "core.lookup", "parameters": {"type": "object"}}],
            "tool_choice": "required",
        },
        turns=[{"role": "user", "content": "hi"}],
        names=names,
        settings=_settings(),
    )

    assert req.payload["tool_choice"] == {"type": "any"}
    assert req.payload["tools"][0]["name"] == "core_lookup"
    assert req.payload["system"] == "base\n\ndev"


def test_anthropic_tool_use_maps_back_to_source_name_and_tool_result_round_trips():
    names = ToolNameMapping(
        model_to_source={"core_lookup": "core.lookup"},
        source_to_model={"core.lookup": "core_lookup"},
    )
    translated = AnthropicTranslator().parse_response(
        data=_fixture("single_tool.json"),
        names=names,
    )

    assert translated.text == "checking"
    assert translated.tool_calls[0].name == "core.lookup"
    assert translated.tool_calls[0].arguments_json == '{"query":"x"}'

    turns = AnthropicTranslator().input_to_turns(
        input_=[{"type": "function_call_output", "call_id": "call_1", "output": "result"}],
        names=names,
    )
    assert turns == [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": "result"}]}]
