from __future__ import annotations

import json
from functools import lru_cache
from typing import Any
from uuid import uuid4

import httpx
from pydantic import AliasChoices, AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ._capabilities import GEMINI_CAPS, ProviderCapabilities
from ._translation import ToolNameMapping, VendorRequest, VendorToolCall, VendorTranslation
from ._translating_provider import TranslatingModelProvider


class GoogleGeminiModelProviderSettings(BaseSettings):
    """
    Google Gemini (Generative Language API) settings.

    Env:
    - GOOGLE_API_KEY or GEMINI_API_KEY
    - GEMINI_BASE_URL (default: https://generativelanguage.googleapis.com/v1beta)
    - ANYAGENT_GEMINI_STATE_MAX (default: 1024)
    """

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    api_key: str = Field(validation_alias=AliasChoices("GOOGLE_API_KEY", "GEMINI_API_KEY"))
    base_url: AnyHttpUrl = Field(
        default="https://generativelanguage.googleapis.com/v1beta",
        alias="GEMINI_BASE_URL",
    )
    state_max_entries: int = Field(default=1024, ge=1, le=100_000, alias="ANYAGENT_GEMINI_STATE_MAX")


class GeminiTranslator:
    capabilities: ProviderCapabilities = GEMINI_CAPS

    def build_request(
        self,
        *,
        body: dict[str, Any],
        turns: list[dict[str, Any]],
        names: ToolNameMapping,
        settings: object,
    ) -> VendorRequest:
        if not isinstance(settings, GoogleGeminiModelProviderSettings):
            raise TypeError("settings must be GoogleGeminiModelProviderSettings")

        generation_config = _generation_config_from_body(body)
        payload: dict[str, Any] = {"contents": turns}
        if generation_config:
            payload["generationConfig"] = generation_config

        system = _system_instruction_from_body(body)
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        tools_req = _to_gemini_tools(body.get("tools") if isinstance(body.get("tools"), list) else [], names)
        if tools_req:
            payload["tools"] = tools_req
            tool_config = _to_gemini_tool_config(body.get("tool_choice"), names)
            if tool_config:
                payload["toolConfig"] = tool_config

        # Pass through workspace extra_params verbatim
        extra_params = body.get("_extra_params")
        if isinstance(extra_params, dict):
            for key, val in extra_params.items():
                if key not in payload:
                    payload[key] = val

        model = str(body["model"]).strip()
        return VendorRequest(
            url_path=f"/models/{model}:generateContent",
            headers={
                "x-goog-api-key": settings.api_key,
                "content-type": "application/json",
            },
            payload=payload,
        )

    def parse_response(self, *, data: dict[str, Any], names: ToolNameMapping) -> VendorTranslation:
        parts = _first_candidate_parts(data)
        text_parts: list[str] = []
        tool_calls: list[VendorToolCall] = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str) and text:
                text_parts.append(text)
            function_call = part.get("functionCall")
            if isinstance(function_call, dict):
                model_name = function_call.get("name")
                if not isinstance(model_name, str):
                    continue
                call_id = function_call.get("id")
                if not isinstance(call_id, str) or not call_id.strip():
                    call_id = f"call_{uuid4().hex}"
                args = function_call.get("args")
                tool_calls.append(
                    VendorToolCall(
                        call_id=call_id,
                        name=names.source_name_for_model(model_name),
                        arguments_json=json.dumps(args if isinstance(args, dict) else {}, ensure_ascii=False, separators=(",", ":")),
                    )
                )
        return VendorTranslation(
            text="".join(text_parts).strip(),
            tool_calls=tool_calls,
            raw_assistant_turn={"role": "model", "parts": parts} if parts else {},
        )

    def input_to_turns(self, *, input_: object, names: ToolNameMapping) -> list[dict[str, Any]]:
        if isinstance(input_, str):
            s = input_.strip()
            return [{"role": "user", "parts": [{"text": s}]}] if s else []

        if not isinstance(input_, list):
            return []

        turns: list[dict[str, Any]] = []
        text_parts: list[dict[str, Any]] = []
        call_id_to_model_name = dict(names.call_id_to_model_name)
        for item in input_:
            if isinstance(item, dict) and item.get("type") == "function_call_output":
                call_id = item.get("call_id")
                output = item.get("output")
                if isinstance(call_id, str) and isinstance(output, str):
                    name = call_id_to_model_name.get(call_id)
                    if isinstance(name, str) and name:
                        turns.append(
                            {
                                "role": "user",
                                "parts": [
                                    {
                                        "functionResponse": {
                                            "name": name,
                                            "response": {"output": output},
                                        }
                                    }
                                ],
                            }
                        )
                continue
            if isinstance(item, dict) and item.get("type") == "function_call":
                call_id = item.get("call_id")
                name = item.get("name")
                arguments = item.get("arguments")
                if isinstance(name, str):
                    model_name = names.model_name_for_source(name)
                    if isinstance(call_id, str) and call_id.strip():
                        call_id_to_model_name[call_id] = model_name
                    turns.append(
                        {
                            "role": "model",
                            "parts": [
                                {
                                    "functionCall": {
                                        "name": model_name,
                                        "args": _json_object(arguments),
                                        **({"id": call_id} if isinstance(call_id, str) else {}),
                                    }
                                }
                            ],
                        }
                    )
                continue
            if isinstance(item, dict) and isinstance(item.get("role"), str):
                role = item.get("role")
                content = item.get("content")
                if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
                    text_parts.append({"text": content.strip()})
                continue

        if text_parts:
            turns.insert(0, {"role": "user", "parts": text_parts})
        return turns


class GoogleGeminiModelProvider(TranslatingModelProvider):
    def __init__(self, *, client: httpx.AsyncClient, settings: GoogleGeminiModelProviderSettings) -> None:
        super().__init__(
            client=client,
            settings=settings,
            translator=GeminiTranslator(),
            base_url=str(settings.base_url).rstrip("/"),
            upstream_name="gemini",
            state_max_entries=settings.state_max_entries,
            request_id_header="x-request-id",
        )


def _generation_config_from_body(body: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    temperature = body.get("temperature")
    if isinstance(temperature, (int, float)):
        out["temperature"] = float(temperature)
    max_tokens = body.get("max_output_tokens")
    if isinstance(max_tokens, int) and max_tokens >= 1:
        out["maxOutputTokens"] = max_tokens
    top_p = body.get("top_p")
    if isinstance(top_p, (int, float)):
        out["topP"] = float(top_p)
    return out


def _system_instruction_from_body(body: dict[str, Any]) -> str | None:
    parts: list[str] = []
    instructions = body.get("instructions")
    if isinstance(instructions, str) and instructions.strip():
        parts.append(instructions.strip())
    input_ = body.get("input")
    if isinstance(input_, list):
        for item in input_:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = item.get("content")
            if role in {"developer", "system"} and isinstance(content, str) and content.strip():
                parts.append(content.strip())
    return "\n\n".join(parts) if parts else None


def _to_gemini_tools(tools: list[object], names: ToolNameMapping) -> list[dict[str, Any]]:
    declarations: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            continue
        name = tool.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        declaration: dict[str, Any] = {
            "name": names.model_name_for_source(name.strip()),
            "description": tool.get("description") or "",
        }
        if isinstance(tool.get("parameters"), dict):
            declaration["parameters"] = tool["parameters"]
        declarations.append(declaration)
    return [{"functionDeclarations": declarations}] if declarations else []


def _to_gemini_tool_config(tool_choice: object, names: ToolNameMapping) -> dict[str, Any] | None:
    if tool_choice is None or tool_choice == "auto":
        mode = "AUTO"
        allowed: list[str] = []
    elif tool_choice == "none":
        mode = "NONE"
        allowed = []
    elif tool_choice == "required":
        mode = "ANY"
        allowed = []
    elif isinstance(tool_choice, dict) and tool_choice.get("type") == "function":
        name = tool_choice.get("name")
        if not isinstance(name, str) or not name.strip():
            return None
        mode = "ANY"
        allowed = [names.model_name_for_source(name.strip())]
    else:
        return None

    cfg: dict[str, Any] = {"mode": mode}
    if allowed:
        cfg["allowedFunctionNames"] = allowed
    return {"functionCallingConfig": cfg}


def _first_candidate_parts(data: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return []
    first = candidates[0]
    if not isinstance(first, dict):
        return []
    content = first.get("content")
    if not isinstance(content, dict):
        return []
    parts = content.get("parts")
    return parts if isinstance(parts, list) else []


def _json_object(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except Exception:  # noqa: BLE001
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def create_google_gemini_model_provider(*, settings: GoogleGeminiModelProviderSettings) -> GoogleGeminiModelProvider:
    client = httpx.AsyncClient()
    return GoogleGeminiModelProvider(client=client, settings=settings)


def get_default_gemini_model_provider(settings: GoogleGeminiModelProviderSettings | None = None) -> GoogleGeminiModelProvider:
    if settings is None:
        settings = GoogleGeminiModelProviderSettings()
    key = (str(settings.base_url).rstrip("/"), settings.api_key, settings.state_max_entries)
    return _cached_default_provider(*key)


@lru_cache(maxsize=8)
def _cached_default_provider(base_url: str, api_key: str, state_max_entries: int) -> GoogleGeminiModelProvider:
    settings = GoogleGeminiModelProviderSettings(
        GEMINI_BASE_URL=base_url,
        GOOGLE_API_KEY=api_key,
        ANYAGENT_GEMINI_STATE_MAX=state_max_entries,
    )
    return create_google_gemini_model_provider(settings=settings)
