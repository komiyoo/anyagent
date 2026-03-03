from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class ModelProviderError(RuntimeError):
    """
    Base error for AnyAgent model providers.

    We deliberately normalize provider-specific SDK errors into a small
    set of typed exceptions so higher layers (agent server / runtime)
    can handle failures consistently.
    """


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


class ModelProvider(Protocol):
    """
    Provider abstraction: returns OpenAI Responses API typed models.

    Important:
    - The AgentRuntime speaks *OpenAI Responses API* at its boundary.
    - Different upstream vendors (OpenAI / Anthropic / Google, etc.)
      can implement this interface using their own SDKs, while AnyAgent
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
