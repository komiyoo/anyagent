from __future__ import annotations

from functools import lru_cache
from typing import Any

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI, AsyncStream
from openai.types.responses.response import Response
from openai.types.responses.response_completed_event import ResponseCompletedEvent
from openai.types.responses.response_stream_event import ResponseStreamEvent

from .base import (
    ModelProvider,
    ModelProviderLiveResponseStream,
    ModelProviderTransportError,
    ModelProviderUpstreamError,
)


class OpenAIResponsesModelProviderSettings(BaseSettings):
    """
    OpenAI-compatible Responses API settings (works for OpenAI or anyagent server).

    Env:
    - OPENAI_API_KEY
    - OPENAI_BASE_URL (default: https://api.openai.com/v1)
    """

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    api_key: str = Field(alias="OPENAI_API_KEY")
    base_url: AnyHttpUrl = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")


class OpenAIResponsesModelProvider(ModelProvider):
    def __init__(self, *, client: AsyncOpenAI) -> None:
        self._client = client

    @staticmethod
    def _extra_body_without_stream(body: dict[str, Any]) -> dict[str, Any]:
        extra_body = dict(body)
        extra_body.pop("stream", None)
        return extra_body

    async def create_response(
        self,
        *,
        body: dict[str, Any],
        idempotency_key: str | None = None,
        timeout_s: float = 60.0,
    ) -> Response:
        extra_headers = {"idempotency-key": idempotency_key} if idempotency_key else None

        try:
            resp = await self._client.responses.create(
                stream=False,
                extra_body=self._extra_body_without_stream(body),
                extra_headers=extra_headers,
                timeout=timeout_s,
            )
        except APIStatusError as e:
            raise ModelProviderUpstreamError(
                status_code=e.status_code,
                body=e.body,
                raw=e.response.content,
                request_id=e.request_id,
                message=str(e),
            ) from e
        except (APITimeoutError, APIConnectionError) as e:
            raise ModelProviderTransportError(str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise ModelProviderTransportError(f"unexpected error: {e}") from e

        if isinstance(resp, Response):
            return resp
        raise ModelProviderTransportError("unexpected streaming response when stream=false")

    async def create_response_stream_buffered(
        self,
        *,
        body: dict[str, Any],
        idempotency_key: str | None = None,
        timeout_s: float | None = None,
    ) -> tuple[list[ResponseStreamEvent], Response]:
        extra_headers = {"idempotency-key": idempotency_key} if idempotency_key else None

        try:
            stream_or_resp = await self._client.responses.create(
                stream=True,
                extra_body=self._extra_body_without_stream(body),
                extra_headers=extra_headers,
                timeout=timeout_s,
            )
        except APIStatusError as e:
            raise ModelProviderUpstreamError(
                status_code=e.status_code,
                body=e.body,
                raw=e.response.content,
                request_id=e.request_id,
                message=str(e),
            ) from e
        except (APITimeoutError, APIConnectionError) as e:
            raise ModelProviderTransportError(str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise ModelProviderTransportError(f"unexpected error: {e}") from e

        if isinstance(stream_or_resp, Response):
            raise ModelProviderTransportError("unexpected non-streaming response when stream=true")
        if not isinstance(stream_or_resp, AsyncStream):
            raise ModelProviderTransportError("unexpected stream type")

        events: list[ResponseStreamEvent] = []
        async with stream_or_resp:
            async for ev in stream_or_resp:
                events.append(ev)

        completed: Response | None = None
        for ev in reversed(events):
            if isinstance(ev, ResponseCompletedEvent):
                completed = ev.response
                break
        if completed is None:
            raise ModelProviderTransportError("missing response.completed in stream")

        return events, completed

    async def create_response_stream_live(
        self,
        *,
        body: dict[str, Any],
        idempotency_key: str | None = None,
        timeout_s: float | None = None,
    ) -> ModelProviderLiveResponseStream:
        extra_headers = {"idempotency-key": idempotency_key} if idempotency_key else None

        try:
            stream_or_resp = await self._client.responses.create(
                stream=True,
                extra_body=self._extra_body_without_stream(body),
                extra_headers=extra_headers,
                timeout=timeout_s,
            )
        except APIStatusError as e:
            raise ModelProviderUpstreamError(
                status_code=e.status_code,
                body=e.body,
                raw=e.response.content,
                request_id=e.request_id,
                message=str(e),
            ) from e
        except (APITimeoutError, APIConnectionError) as e:
            raise ModelProviderTransportError(str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise ModelProviderTransportError(f"unexpected error: {e}") from e

        if isinstance(stream_or_resp, Response):
            raise ModelProviderTransportError("unexpected non-streaming response when stream=true")
        if not isinstance(stream_or_resp, AsyncStream):
            raise ModelProviderTransportError("unexpected stream type")
        return _OpenAILiveResponseStream(stream=stream_or_resp)


class _OpenAILiveResponseStream(ModelProviderLiveResponseStream):
    def __init__(self, *, stream: AsyncStream[ResponseStreamEvent]) -> None:
        self._stream = stream
        self._completed: Response | None = None
        self._entered = False
        self._finished = False

    async def __aenter__(self) -> "_OpenAILiveResponseStream":
        await self._stream.__aenter__()
        self._entered = True
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._entered:
            await self._stream.__aexit__(exc_type, exc, tb)
        self._finished = True

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        async for ev in self._stream:
            if isinstance(ev, ResponseCompletedEvent):
                self._completed = ev.response
            yield ev
        self._finished = True

    async def wait_completed(self) -> Response:
        if self._completed is not None:
            return self._completed
        if self._finished:
            raise ModelProviderTransportError("missing response.completed in stream")
        raise ModelProviderTransportError("wait_completed called before stream finished")


def create_openai_responses_model_provider(
    *, settings: OpenAIResponsesModelProviderSettings
) -> OpenAIResponsesModelProvider:
    client = AsyncOpenAI(api_key=settings.api_key, base_url=str(settings.base_url).rstrip("/"))
    return OpenAIResponsesModelProvider(client=client)


def get_default_model_provider(
    settings: OpenAIResponsesModelProviderSettings | None = None,
) -> OpenAIResponsesModelProvider:
    """
    Default singleton-ish provider (cache keyed by settings values).

    Note: Caches by (base_url, api_key).
    """
    if settings is None:
        settings = OpenAIResponsesModelProviderSettings()
    key = (str(settings.base_url).rstrip("/"), settings.api_key)
    return _cached_default_provider(*key)


@lru_cache(maxsize=8)
def _cached_default_provider(base_url: str, api_key: str) -> OpenAIResponsesModelProvider:
    settings = OpenAIResponsesModelProviderSettings(
        OPENAI_BASE_URL=base_url,
        OPENAI_API_KEY=api_key,
    )
    return create_openai_responses_model_provider(settings=settings)
