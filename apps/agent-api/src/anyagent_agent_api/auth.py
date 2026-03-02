from __future__ import annotations

from fastapi import Request
from fastapi.responses import Response

from .errors import openai_error
from .settings import Settings


async def check_api_key(request: Request, settings: Settings) -> Response | None:
    auth = request.headers.get("authorization")
    if not auth:
        return openai_error(401, message="Missing Authorization header", type_="authentication_error")

    parts = auth.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return openai_error(401, message="Invalid Authorization header", type_="authentication_error")

    token = parts[1].strip()
    if token != settings.agent_api_key:
        return openai_error(401, message="Invalid API key", type_="authentication_error")

    return None
