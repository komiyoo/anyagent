from __future__ import annotations

from fastapi import Request
from fastapi.responses import Response

from .errors import tool_error
from ..settings import Settings


async def check_internal_auth(request: Request, settings: Settings) -> Response | None:
    auth = request.headers.get("authorization")
    if not auth:
        return tool_error(
            status_code=401,
            type_="tool_auth_error",
            code="missing_authorization",
            message="Missing Authorization header",
            retryable=False,
        )

    parts = auth.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return tool_error(
            status_code=401,
            type_="tool_auth_error",
            code="invalid_authorization",
            message="Invalid Authorization header",
            retryable=False,
        )

    if parts[1].strip() != settings.tool_runtime_internal_key:
        return tool_error(
            status_code=401,
            type_="tool_auth_error",
            code="invalid_key",
            message="Invalid internal key",
            retryable=False,
        )

    return None
