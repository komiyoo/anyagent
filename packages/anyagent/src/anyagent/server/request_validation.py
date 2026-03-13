from __future__ import annotations

from typing import Any

from anyagent.protocol.openai_responses import AnyAgentFunctionToolParam


class ResponsesRequestValidationError(ValueError):
    """Raised when a Responses API request body is structurally invalid."""


def ensure_request_body_object(
    body: Any,
    *,
    message: str = "request body must be an object",
) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ResponsesRequestValidationError(message)
    return body


def ensure_metadata_object(
    body: dict[str, Any],
    *,
    message: str = "metadata must be an object",
) -> dict[str, Any] | None:
    metadata = body.get("metadata")
    if metadata is None:
        return None
    if not isinstance(metadata, dict):
        raise ResponsesRequestValidationError(message)
    return metadata


def parse_function_tools(
    raw_tools: Any,
    *,
    list_message: str = "tools must be a list",
    item_error_prefix: str = "invalid tools",
) -> list[AnyAgentFunctionToolParam] | None:
    if raw_tools is None:
        return None
    if not isinstance(raw_tools, list):
        raise ResponsesRequestValidationError(list_message)

    parsed: list[AnyAgentFunctionToolParam] = []
    for index, item in enumerate(raw_tools):
        try:
            parsed.append(AnyAgentFunctionToolParam.model_validate(item))
        except Exception as exc:  # noqa: BLE001
            raise ResponsesRequestValidationError(f"{item_error_prefix}[{index}]: {exc}") from exc
    return parsed
