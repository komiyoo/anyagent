from __future__ import annotations

import json
from pathlib import Path

from anyagent.agent_runtime.model_providers._translation import ToolNameMapping
from anyagent.agent_runtime.model_providers.google_gemini import GeminiTranslator, GoogleGeminiModelProviderSettings


def _settings() -> GoogleGeminiModelProviderSettings:
    return GoogleGeminiModelProviderSettings(
        GOOGLE_API_KEY="test-key",
        GEMINI_BASE_URL="https://example.test/v1beta",
    )


def _fixture(name: str) -> dict:
    path = Path(__file__).parents[3] / "fixtures" / "model_providers" / "gemini" / name
    return json.loads(path.read_text(encoding="utf-8"))


def test_gemini_tools_tool_choice_and_system_instruction_are_translated():
    names = ToolNameMapping(
        model_to_source={"core_lookup": "core.lookup"},
        source_to_model={"core.lookup": "core_lookup"},
    )
    req = GeminiTranslator().build_request(
        body={
            "model": "gemini-test",
            "instructions": "base",
            "input": [{"role": "developer", "content": "dev"}, {"role": "user", "content": "hi"}],
            "tools": [{"type": "function", "name": "core.lookup", "parameters": {"type": "object"}}],
            "tool_choice": {"type": "function", "name": "core.lookup"},
        },
        turns=[{"role": "user", "parts": [{"text": "hi"}]}],
        names=names,
        settings=_settings(),
    )

    declaration = req.payload["tools"][0]["functionDeclarations"][0]
    assert declaration["name"] == "core_lookup"
    assert req.payload["toolConfig"] == {
        "functionCallingConfig": {"mode": "ANY", "allowedFunctionNames": ["core_lookup"]}
    }
    assert req.payload["systemInstruction"] == {"parts": [{"text": "base\n\ndev"}]}


def test_gemini_function_call_and_function_response_round_trip():
    names = ToolNameMapping(
        model_to_source={"core_lookup": "core.lookup"},
        source_to_model={"core.lookup": "core_lookup"},
        call_id_to_model_name={"call_1": "core_lookup"},
    )
    translated = GeminiTranslator().parse_response(
        data=_fixture("single_tool.json"),
        names=names,
    )

    assert translated.text == "checking"
    assert translated.tool_calls[0].name == "core.lookup"
    assert translated.tool_calls[0].arguments_json == '{"query":"x"}'

    turns = GeminiTranslator().input_to_turns(
        input_=[{"type": "function_call_output", "call_id": "call_1", "output": "result"}],
        names=names,
    )
    assert turns == [
        {
            "role": "user",
            "parts": [{"functionResponse": {"name": "core_lookup", "response": {"output": "result"}}}],
        }
    ]


def test_gemini_stateless_retry_input_uses_function_call_name_for_output():
    names = ToolNameMapping(
        model_to_source={"core_lookup": "core.lookup"},
        source_to_model={"core.lookup": "core_lookup"},
    )

    turns = GeminiTranslator().input_to_turns(
        input_=[
            {"type": "function_call", "call_id": "call_1", "name": "core.lookup", "arguments": '{"query":"x"}'},
            {"type": "function_call_output", "call_id": "call_1", "output": "result"},
        ],
        names=names,
    )

    assert turns == [
        {
            "role": "model",
            "parts": [{"functionCall": {"name": "core_lookup", "args": {"query": "x"}, "id": "call_1"}}],
        },
        {
            "role": "user",
            "parts": [{"functionResponse": {"name": "core_lookup", "response": {"output": "result"}}}],
        },
    ]
