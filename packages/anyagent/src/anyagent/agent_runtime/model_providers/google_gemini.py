from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from uuid import uuid4

import httpx
from pydantic import AliasChoices, AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from openai.types.responses.response import Response
from openai.types.responses.response_completed_event import ResponseCompletedEvent
from openai.types.responses.response_created_event import ResponseCreatedEvent
from openai.types.responses.response_output_message import ResponseOutputMessage
from openai.types.responses.response_output_text import ResponseOutputText
from openai.types.responses.response_stream_event import ResponseStreamEvent

from .base import (
    ModelProvider,
    ModelProviderInvalidRequestError,
    ModelProviderTransportError,
    ModelProviderUpstreamError,
)


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


@dataclass(slots=True)
class _ConversationState:
    contents: list[dict[str, Any]]


class GoogleGeminiModelProvider(ModelProvider):
    """
    ModelProvider backed by Google Gemini `generateContent`.

    Notes:
    - Uses an in-memory conversation store to emulate `previous_response_id`.
    - Currently focuses on text completion (tool calling is not implemented).
    """

    def __init__(self, *, client: httpx.AsyncClient, settings: GoogleGeminiModelProviderSettings) -> None:
        self._client = client
        self._settings = settings
        self._state: "OrderedDict[str, _ConversationState]" = OrderedDict()
        self._idem: dict[str, Response] = {}

    async def create_response(
        self,
        *,
        body: dict[str, Any],
        idempotency_key: str | None = None,
        timeout_s: float = 60.0,
    ) -> Response:
        if idempotency_key and idempotency_key in self._idem:
            return self._idem[idempotency_key]

        try:
            resp = await self._create_response_impl(body=body, timeout_s=timeout_s)
        except httpx.TimeoutException as e:
            raise ModelProviderTransportError(str(e)) from e
        except httpx.RequestError as e:
            raise ModelProviderTransportError(str(e)) from e

        if idempotency_key:
            self._idem[idempotency_key] = resp
        return resp

    async def create_response_stream_buffered(
        self,
        *,
        body: dict[str, Any],
        idempotency_key: str | None = None,
        timeout_s: float | None = None,
    ) -> tuple[list[ResponseStreamEvent], Response]:
        resp = await self.create_response(body=body, idempotency_key=idempotency_key, timeout_s=timeout_s or 60.0)
        created = ResponseCreatedEvent(type="response.created", sequence_number=0, response=resp)
        completed = ResponseCompletedEvent(type="response.completed", sequence_number=1, response=resp)
        return [created, completed], resp

    async def _create_response_impl(self, *, body: dict[str, Any], timeout_s: float) -> Response:
        model = body.get("model")
        if not isinstance(model, str) or not model.strip():
            raise ModelProviderInvalidRequestError("missing body.model")
        model = model.strip()

        previous_response_id = body.get("previous_response_id")
        prev_id = previous_response_id.strip() if isinstance(previous_response_id, str) and previous_response_id.strip() else None

        input_ = body.get("input")
        if prev_id is None:
            conv = _ConversationState(contents=_input_to_gemini_contents(input_))
        else:
            prev = self._state.get(prev_id)
            if prev is None:
                raise ModelProviderInvalidRequestError(f"unknown previous_response_id: {prev_id}")
            followup = _input_to_gemini_contents(input_)
            conv = _ConversationState(contents=[*prev.contents, *followup])

        gen_cfg: dict[str, Any] = {}
        temperature = body.get("temperature")
        if isinstance(temperature, (int, float)):
            gen_cfg["temperature"] = float(temperature)
        max_tokens = body.get("max_output_tokens")
        if isinstance(max_tokens, int) and 1 <= max_tokens <= 8192:
            gen_cfg["maxOutputTokens"] = max_tokens
        top_p = body.get("top_p")
        if isinstance(top_p, (int, float)):
            gen_cfg["topP"] = float(top_p)

        payload: dict[str, Any] = {"contents": conv.contents}
        if gen_cfg:
            payload["generationConfig"] = gen_cfg

        url = str(self._settings.base_url).rstrip("/") + f"/models/{model}:generateContent"
        r = await self._client.post(
            url,
            headers={
                "x-goog-api-key": self._settings.api_key,
                "content-type": "application/json",
            },
            json=payload,
            timeout=timeout_s,
        )

        if r.status_code >= 400:
            body_obj: object | None
            try:
                body_obj = r.json()
            except Exception:  # noqa: BLE001
                body_obj = {"error": {"message": r.text}}
            raise ModelProviderUpstreamError(
                status_code=r.status_code,
                body=body_obj,
                raw=r.content,
                request_id=r.headers.get("x-request-id"),
                message="gemini upstream error",
            )

        data = r.json()
        text = _extract_gemini_text(data)
        if not text:
            text = ""

        resp_id = f"resp_{uuid4().hex}"
        created_at = int(time.time())
        tool_choice_resp = body.get("tool_choice") if body.get("tool_choice") is not None else "auto"
        tools_resp = body.get("tools") if isinstance(body.get("tools"), list) else []
        parallel_tool_calls = body.get("parallel_tool_calls")
        parallel = bool(parallel_tool_calls) if isinstance(parallel_tool_calls, bool) else False

        out_items: list[dict[str, Any]] = []
        if text.strip():
            out_items.append(
                ResponseOutputMessage(
                    id=f"msg_{uuid4().hex}",
                    type="message",
                    role="assistant",
                    status="completed",
                    content=[ResponseOutputText(type="output_text", text=text.strip(), annotations=[])],
                ).model_dump(exclude_none=True, by_alias=True)
            )

        response_payload: dict[str, Any] = {
            "id": resp_id,
            "object": "response",
            "created_at": created_at,
            "model": model,
            "output": out_items,
            "parallel_tool_calls": parallel,
            "tool_choice": tool_choice_resp,
            "tools": tools_resp,
        }
        resp = Response.model_validate(response_payload)

        self._remember(resp_id, conv.contents, assistant_text=text.strip())
        return resp

    def _remember(self, response_id: str, contents: list[dict[str, Any]], *, assistant_text: str) -> None:
        new_contents = list(contents)
        if assistant_text:
            new_contents.append({"role": "model", "parts": [{"text": assistant_text}]})
        self._state[response_id] = _ConversationState(contents=new_contents)
        self._state.move_to_end(response_id)
        while len(self._state) > self._settings.state_max_entries:
            self._state.popitem(last=False)


def _input_to_gemini_contents(input_: object) -> list[dict[str, Any]]:
    if isinstance(input_, str):
        s = input_.strip()
        if not s:
            return []
        return [{"role": "user", "parts": [{"text": s}]}]

    if isinstance(input_, list):
        # Best-effort: collapse list input into user text parts.
        parts: list[dict[str, Any]] = []
        for item in input_:
            if isinstance(item, dict) and item.get("type") == "function_call_output":
                # Tool outputs are modeled as plain user-visible text for now.
                call_id = item.get("call_id")
                output = item.get("output")
                if isinstance(call_id, str) and isinstance(output, str):
                    parts.append({"text": f"[tool_call_output call_id={call_id}]\\n{output}"})
                continue
            if isinstance(item, dict) and isinstance(item.get("content"), str):
                parts.append({"text": item.get("content", "")})
        if parts:
            return [{"role": "user", "parts": parts}]
        return []

    return []


def _extract_gemini_text(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    cands = payload.get("candidates")
    if not isinstance(cands, list) or not cands:
        return None
    cand0 = cands[0]
    if not isinstance(cand0, dict):
        return None
    content = cand0.get("content")
    if not isinstance(content, dict):
        return None
    parts = content.get("parts")
    if not isinstance(parts, list):
        return None
    texts: list[str] = []
    for p in parts:
        if isinstance(p, dict) and isinstance(p.get("text"), str):
            texts.append(p["text"])
    return "".join(texts)


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

