from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol


class ModelProviderError(RuntimeError):
    """
    Base error for anyagent model providers.

    We deliberately normalize provider-specific SDK errors into a small
    set of typed exceptions so higher layers (agent server / runtime)
    can handle failures consistently.
    """

    def __str__(self) -> str:
        msg = getattr(self, "message", None)
        if isinstance(msg, str) and msg.strip():
            return msg
        return super().__str__() or type(self).__name__


@dataclass(slots=True)
class ModelProviderInvalidRequestError(ModelProviderError):
    message: str


@dataclass(slots=True)
class ModelProviderTransportError(ModelProviderError):
    message: str


@dataclass(slots=True)
class ModelProviderUpstreamError(ModelProviderError):
    status_code: int
    body: object | None
    raw: bytes | None = None
    request_id: str | None = None
    message: str | None = None


class ModelProviderLiveResponseStream(Protocol):
    async def __aenter__(self) -> "ModelProviderLiveResponseStream":
        raise NotImplementedError

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        raise NotImplementedError

    def __aiter__(self) -> AsyncIterator["openai.types.responses.response_stream_event.ResponseStreamEvent"]:
        raise NotImplementedError

    async def wait_completed(self) -> "openai.types.responses.response.Response":
        raise NotImplementedError


@dataclass(slots=True)
class BufferedLiveResponseStream:
    events: list["openai.types.responses.response_stream_event.ResponseStreamEvent"]
    completed: "openai.types.responses.response.Response"

    async def __aenter__(self) -> "BufferedLiveResponseStream":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def __aiter__(self) -> AsyncIterator["openai.types.responses.response_stream_event.ResponseStreamEvent"]:
        return self._iter()

    async def _iter(self) -> AsyncIterator["openai.types.responses.response_stream_event.ResponseStreamEvent"]:
        for ev in self.events:
            yield ev

    async def wait_completed(self) -> "openai.types.responses.response.Response":
        return self.completed


class ModelProvider(Protocol):
    """
    Provider abstraction: returns OpenAI Responses API typed models.

    Important:
    - The AgentRuntime speaks *OpenAI Responses API* at its boundary.
    - Different upstream vendors (OpenAI / Anthropic / Google, etc.)
      can implement this interface using their own SDKs, while anyagent
      keeps a single protocol surface.
    """

    async def create_response(
        self,
        *,
        body: dict[str, Any],
        idempotency_key: str | None = None,
        timeout_s: float = 60.0,
    ) -> "openai.types.responses.response.Response":
        raise NotImplementedError

    async def create_response_stream_buffered(
        self,
        *,
        body: dict[str, Any],
        idempotency_key: str | None = None,
        timeout_s: float | None = None,
    ) -> tuple[
        list["openai.types.responses.response_stream_event.ResponseStreamEvent"],
        "openai.types.responses.response.Response",
    ]:
        """
        Execute `POST /v1/responses` with `stream=true` and buffer all events in memory.

        Returns (events, completed_response).
        """
        raise NotImplementedError

    async def create_response_stream_live(
        self,
        *,
        body: dict[str, Any],
        idempotency_key: str | None = None,
        timeout_s: float | None = None,
    ) -> ModelProviderLiveResponseStream:
        raise NotImplementedError
