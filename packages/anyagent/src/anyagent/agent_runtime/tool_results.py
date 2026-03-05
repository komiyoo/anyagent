from __future__ import annotations

import json
from typing import Any, Literal, Mapping


def coerce_tool_result(value: Any) -> dict[str, Any]:
    """Coerce a candidate tool result into a dict payload."""

    if isinstance(value, dict):
        return value
    return {}


def build_completed_tool_result(*, output: str) -> dict[str, Any]:
    """Build a normalized completed tool result payload."""

    return {"status": "completed", "output": output}


def build_error_tool_result(
    *,
    error_type: str,
    message: str,
    code: str | None = None,
    retryable: bool | None = None,
    status: str = "error",
) -> dict[str, Any]:
    """Build a normalized errored tool result payload."""

    error: dict[str, Any] = {"type": error_type, "message": message}
    if isinstance(code, str) and code.strip():
        error["code"] = code.strip()
    if isinstance(retryable, bool):
        error["retryable"] = retryable
    return {"status": status, "error": error}


def tool_result_to_output_text(
    *,
    tool_result: Mapping[str, Any],
    error_format: Literal["repr", "json"] = "repr",
) -> str:
    """Convert a tool result payload to OpenAI function_call_output text."""

    status = tool_result.get("status")
    output = tool_result.get("output")
    if status == "completed" and isinstance(output, str):
        return output

    payload = {"error": tool_result.get("error"), "status": status}
    if error_format == "json":
        return json.dumps(payload, ensure_ascii=False)
    return str(payload)


def build_function_call_output_item(
    *,
    call_id: str,
    tool_result: Mapping[str, Any],
    error_format: Literal["repr", "json"] = "repr",
) -> dict[str, str]:
    """Build one Responses `function_call_output` item from a tool result."""

    return {
        "type": "function_call_output",
        "call_id": call_id,
        "output": tool_result_to_output_text(tool_result=tool_result, error_format=error_format),
    }
