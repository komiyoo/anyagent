from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from openai.types.responses.response import Response
from openai.types.responses.response_function_tool_call import ResponseFunctionToolCall
from openai.types.responses.response_output_message import ResponseOutputMessage
from openai.types.responses.response_output_text import ResponseOutputText
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.settings import ModelSettings

from anyagent.model_config import EffectiveModelSelection, ModelConfigError
from anyagent.protocol.tool_manifest_extensions import model_tool_name_for_name

from ..model_providers import (
    ModelProvider,
    ModelProviderInvalidRequestError,
    ModelProviderTransportError,
    ModelProviderUpstreamError,
)
from ..model_providers.openai_responses import OpenAIResponsesModelProvider
from ..tool_loop_payloads import build_tool_loop_followup_body

# models.yaml provider.kind → pydantic-ai model-string prefix (v2: openai: is Responses).
_PYDANTIC_AI_KIND_PREFIX: dict[str, str] = {
    "openai": "openai",
    "openai_chat": "openai-chat",
    "anthropic": "anthropic",
    "gemini": "google",
}


@dataclass(frozen=True, slots=True)
class PydanticAIModelHandle:
    """Marker used on the Responses path instead of vendor HTTP translators."""

    selection: EffectiveModelSelection


def pydantic_ai_model_id(*, provider_kind: str, model: str | None) -> str:
    """Map a workspace provider kind + model name to a pydantic-ai model string.

    Unknown kinds fail fast; an empty model id also fails.
    """

    kind = (provider_kind or "").strip().lower()
    prefix = _PYDANTIC_AI_KIND_PREFIX.get(kind)
    if prefix is None:
        raise ModelConfigError(
            f"unmapped models.yaml provider kind {provider_kind!r}; "
            f"supported kinds: {sorted(_PYDANTIC_AI_KIND_PREFIX)}"
        )
    name = (model or "").strip()
    if not name:
        raise ModelConfigError(f"missing model id for provider kind {provider_kind!r}")
    return f"{prefix}:{name}"


def model_settings_from_body(body: dict[str, Any]) -> ModelSettings | None:
    kwargs: dict[str, Any] = {}
    temperature = body.get("temperature")
    if isinstance(temperature, (int, float)):
        kwargs["temperature"] = float(temperature)
    top_p = body.get("top_p")
    if isinstance(top_p, (int, float)):
        kwargs["top_p"] = float(top_p)
    max_output_tokens = body.get("max_output_tokens")
    if isinstance(max_output_tokens, int) and max_output_tokens > 0:
        kwargs["max_tokens"] = max_output_tokens
    extra = body.get("_extra_params")
    if isinstance(extra, dict) and extra:
        kwargs["extra_body"] = extra
    return ModelSettings(**kwargs) if kwargs else None


def resolve_pydantic_ai_model(
    model_provider: Any,
    *,
    body: dict[str, Any],
) -> Model:
    """Pick the pydantic-ai Model for this loop invocation."""

    if isinstance(model_provider, Model):
        return model_provider
    if isinstance(model_provider, PydanticAIModelHandle):
        return _model_from_selection(model_provider.selection, request_model=_request_model(body))
    if isinstance(model_provider, OpenAIResponsesModelProvider):
        return _openai_responses_from_provider(model_provider, request_model=_request_model(body))
    if hasattr(model_provider, "create_response"):
        return ModelProviderBridgeModel(
            model_provider,
            original_body=body,
            model_name=_request_model(body) or "unknown",
        )
    raise ModelConfigError(f"cannot resolve pydantic-ai model from provider {type(model_provider)!r}")


def _request_model(body: dict[str, Any]) -> str | None:
    value = body.get("model")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _model_from_selection(selection: EffectiveModelSelection, *, request_model: str | None) -> Model:
    model_name = request_model or selection.model
    model_id = pydantic_ai_model_id(provider_kind=selection.provider_kind, model=model_name)
    api_key = _env_value(selection.api_key_env)
    base_url = selection.base_url or _env_value(selection.base_url_env)
    if selection.provider_kind in {"openai", "openai_chat"} and (api_key or base_url):
        from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
        from pydantic_ai.providers.openai import OpenAIProvider

        provider = OpenAIProvider(api_key=api_key, base_url=base_url)
        if selection.provider_kind == "openai_chat":
            return OpenAIChatModel(model_name or "unknown", provider=provider)
        return OpenAIResponsesModel(model_name or "unknown", provider=provider)
    if selection.provider_kind == "anthropic" and (api_key or base_url):
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.providers.anthropic import AnthropicProvider

        return AnthropicModel(model_name or "unknown", provider=AnthropicProvider(api_key=api_key, base_url=base_url))
    if selection.provider_kind == "gemini" and (api_key or base_url):
        from pydantic_ai.models.google import GoogleModel
        from pydantic_ai.providers.google import GoogleProvider

        return GoogleModel(model_name or "unknown", provider=GoogleProvider(api_key=api_key, base_url=base_url))
    return _infer_native(model_id)


def _openai_responses_from_provider(provider: OpenAIResponsesModelProvider, *, request_model: str | None) -> Model:
    from pydantic_ai.models.openai import OpenAIResponsesModel
    from pydantic_ai.providers.openai import OpenAIProvider

    model_name = request_model or "unknown"
    client = getattr(provider, "_client", None)
    if client is not None:
        return OpenAIResponsesModel(model_name, provider=OpenAIProvider(openai_client=client))
    return _infer_native(pydantic_ai_model_id(provider_kind="openai", model=model_name))


def _infer_native(model_id: str) -> Model:
    from pydantic_ai.models import infer_model

    return infer_model(model_id)


def _env_value(name: str | None) -> str | None:
    if not name:
        return None
    value = os.getenv(name)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _is_previous_response_not_found(error: ModelProviderUpstreamError) -> bool:
    body = error.body
    if not isinstance(body, dict):
        return False
    code = body.get("code")
    param = body.get("param")
    message = body.get("message")
    return (
        code == "InvalidParameter.PreviousResponseNotFound"
        or param == "previous_response_id"
        and isinstance(message, str)
        and "not found" in message.lower()
    )


class ModelProviderBridgeModel(Model):
    """pydantic-ai Model that forwards to an injected ModelProvider (test fakes)."""

    def __init__(
        self,
        provider: ModelProvider,
        *,
        original_body: dict[str, Any],
        model_name: str,
        idempotency_key: str | None = None,
    ) -> None:
        super().__init__()
        self._model_provider = provider
        self._original_body = dict(original_body)
        self._model_name = model_name
        self._idempotency_key = idempotency_key
        self._first = True
        self._last_response: Response | None = None
        self._first_response_id: str | None = None

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def system(self) -> str:
        return "openai"

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        _ = model_settings, model_request_parameters
        body, is_first = self._next_body(messages)
        try:
            resp = await self._model_provider.create_response(
                body=body,
                idempotency_key=self._idempotency_key if is_first else None,
            )
        except ModelProviderUpstreamError as e:
            if not is_first and _is_previous_response_not_found(e) and self._last_response is not None:
                fallback = self._stateless_followup_body(messages)
                resp = await self._model_provider.create_response(body=fallback, idempotency_key=None)
            else:
                raise
        self._last_response = resp
        if self._first_response_id is None and isinstance(resp.id, str) and resp.id.strip():
            self._first_response_id = resp.id.strip()
        if isinstance(resp.model, str) and resp.model.strip():
            self._model_name = resp.model.strip()
        return openai_response_to_model_response(resp)

    def _next_body(self, messages: list[ModelMessage]) -> tuple[dict[str, Any], bool]:
        if self._first:
            self._first = False
            return dict(self._original_body), True
        tool_outputs = _tool_outputs_from_messages(messages)
        previous_id = None
        if self._last_response is not None and isinstance(self._last_response.id, str):
            previous_id = self._last_response.id
        next_body = build_tool_loop_followup_body(
            previous_response_id=previous_id or "resp_anyagent",
            tool_outputs=tool_outputs,
            manifest_tools=list(self._original_body.get("tools") or []),
            metadata=self._original_body.get("metadata"),
            tool_choice=self._original_body.get("tool_choice"),
            stream=self._original_body.get("stream"),
            model=self._original_body.get("model") if isinstance(self._original_body.get("model"), str) else None,
            prompt_cache_key=self._original_body.get("prompt_cache_key")
            if isinstance(self._original_body.get("prompt_cache_key"), str)
            else None,
        )
        next_body.pop("metadata", None)
        return next_body, False

    def _stateless_followup_body(self, messages: list[ModelMessage]) -> dict[str, Any]:
        tool_outputs = _tool_outputs_from_messages(messages)
        body = dict(self._original_body)
        body.pop("previous_response_id", None)
        prior: list[Any] = []
        if self._last_response is not None:
            dumped = self._last_response.model_dump(exclude_none=True, by_alias=True).get("output")
            if isinstance(dumped, list):
                prior = list(dumped)
        body["input"] = [*prior, *tool_outputs]
        return body


def _tool_outputs_from_messages(messages: list[ModelMessage]) -> list[dict[str, str]]:
    for message in reversed(messages):
        if not isinstance(message, ModelRequest):
            continue
        outputs: list[dict[str, str]] = []
        for part in message.parts:
            if isinstance(part, ToolReturnPart):
                content = part.content
                if not isinstance(content, str):
                    content = json.dumps(content, ensure_ascii=False)
                outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": part.tool_call_id,
                        "output": content,
                    }
                )
        if outputs:
            return outputs
    return []


def openai_response_to_model_response(resp: Response) -> ModelResponse:
    parts: list[Any] = []
    for item in resp.output:
        if isinstance(item, ResponseFunctionToolCall):
            name = item.name if isinstance(item.name, str) else "tool"
            parts.append(
                ToolCallPart(
                    tool_name=model_tool_name_for_name(name),
                    args=item.arguments,
                    tool_call_id=item.call_id or "",
                )
            )
            continue
        if isinstance(item, ResponseOutputMessage):
            for content in item.content:
                if isinstance(content, ResponseOutputText) and content.text:
                    parts.append(TextPart(content=content.text))
            continue
        if isinstance(item, dict):
            item_type = item.get("type")
            if item_type == "function_call":
                raw_name = item.get("name")
                name = raw_name if isinstance(raw_name, str) else "tool"
                parts.append(
                    ToolCallPart(
                        tool_name=model_tool_name_for_name(name),
                        args=item.get("arguments") or {},
                        tool_call_id=str(item.get("call_id") or ""),
                    )
                )
            elif item_type == "message":
                for content in item.get("content") or []:
                    if isinstance(content, dict) and isinstance(content.get("text"), str) and content["text"]:
                        parts.append(TextPart(content=content["text"]))
    if not parts:
        parts = [TextPart(content="")]
    model_name = resp.model if isinstance(resp.model, str) and resp.model.strip() else "unknown"
    return ModelResponse(parts=parts, model_name=model_name, provider_response_id=resp.id)


def extract_instructions_from_body(body: dict[str, Any]) -> str:
    """Build pydantic-ai instructions from the already-assembled prompt envelope in `body`."""

    parts: list[str] = []
    instructions = body.get("instructions")
    if isinstance(instructions, str) and instructions.strip():
        parts.append(instructions.strip())
    inp = body.get("input")
    if isinstance(inp, list):
        for item in inp:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            if role not in {"developer", "system"}:
                continue
            content = item.get("content")
            text = _content_to_text(content)
            if text:
                parts.append(text)
    return "\n\n".join(parts)


def split_user_prompt_and_history(body: dict[str, Any]) -> tuple[str | None, list[ModelMessage] | None]:
    """Split Responses `input` into current user_prompt + prior message_history.

    The current user turn is sent once as `user_prompt`. Earlier turns stay in
    `message_history`. A list that already ends on an assistant/tool item has
    no new user turn (`user_prompt` is None).
    """

    inp = body.get("input")
    if isinstance(inp, str):
        return (inp if inp else " "), None
    if inp is None:
        return " ", None
    if not isinstance(inp, list):
        return str(inp), None

    last_user_idx: int | None = None
    for index, item in enumerate(inp):
        if isinstance(item, dict) and item.get("role") == "user":
            last_user_idx = index
    if last_user_idx is None:
        return None, _messages_from_input_items(inp)

    trailing: list[dict[str, Any]] = []
    for item in inp[last_user_idx + 1 :]:
        if not isinstance(item, dict):
            continue
        if item.get("role") in {"developer", "system"}:
            continue
        trailing.append(item)
    if trailing:
        return None, _messages_from_input_items(inp)

    prompt = _content_to_text(inp[last_user_idx].get("content")) or " "
    history = _messages_from_input_items(inp[:last_user_idx])
    return prompt, history


def _content_to_text(content: Any) -> str:
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        chunks: list[str] = []
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str) and part["text"].strip():
                chunks.append(part["text"].strip())
            elif isinstance(part, str) and part.strip():
                chunks.append(part.strip())
        return "\n".join(chunks)
    return ""


def _messages_from_input_items(items: list[Any]) -> list[ModelMessage] | None:
    history: list[ModelMessage] = []
    pending_request_parts: list[Any] = []
    pending_response_parts: list[Any] = []

    def flush_request() -> None:
        nonlocal pending_request_parts
        if pending_request_parts:
            history.append(ModelRequest(parts=list(pending_request_parts)))
            pending_request_parts = []

    def flush_response() -> None:
        nonlocal pending_response_parts
        if pending_response_parts:
            history.append(ModelResponse(parts=list(pending_response_parts)))
            pending_response_parts = []

    for item in items:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        item_type = item.get("type")
        if role in {"developer", "system"}:
            continue
        if role == "user":
            flush_response()
            text = _content_to_text(item.get("content"))
            if text:
                pending_request_parts.append(UserPromptPart(content=text))
            continue
        if role == "assistant" or item_type == "message":
            flush_request()
            text = _content_to_text(item.get("content"))
            if text:
                pending_response_parts.append(TextPart(content=text))
            continue
        if item_type == "function_call":
            flush_request()
            raw_name = item.get("name")
            name = raw_name if isinstance(raw_name, str) else "tool"
            pending_response_parts.append(
                ToolCallPart(
                    tool_name=model_tool_name_for_name(name),
                    args=item.get("arguments") or {},
                    tool_call_id=str(item.get("call_id") or ""),
                )
            )
            continue
        if item_type == "function_call_output":
            flush_response()
            pending_request_parts.append(
                ToolReturnPart(
                    tool_name="tool",
                    content=str(item.get("output") or ""),
                    tool_call_id=str(item.get("call_id") or ""),
                )
            )
    flush_response()
    flush_request()
    return history or None
