from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import Request
from fastapi.responses import Response, StreamingResponse

from ..settings import Settings


HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-length",
    "content-encoding",
}


def _forward_headers_from_upstream(upstream: httpx.Response) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in upstream.headers.items():
        lk = k.lower()
        if lk in HOP_BY_HOP_HEADERS:
            continue
        out[k] = v
    return out


def _pick_upstream_headers(request: Request, settings: Settings) -> dict[str, str]:
    headers: dict[str, str] = {
        "authorization": f"Bearer {settings.openai_api_key}",
        "content-type": "application/json",
    }
    idem = request.headers.get("idempotency-key")
    if idem:
        headers["idempotency-key"] = idem
    return headers


async def proxy_responses(
    *,
    client: httpx.AsyncClient,
    request: Request,
    settings: Settings,
    body: Any,
) -> Response:
    url = str(settings.openai_base_url).rstrip("/") + "/responses"

    async with client.stream("POST", url, headers=_pick_upstream_headers(request, settings), json=body) as upstream:
        headers = _forward_headers_from_upstream(upstream)
        content_type = upstream.headers.get("content-type")

        async def iter_bytes() -> AsyncIterator[bytes]:
            async for chunk in upstream.aiter_bytes():
                if await request.is_disconnected():
                    break
                yield chunk

        # upstream 可能是 SSE（stream=true）或 JSON。这里统一用 StreamingResponse 透传。
        return StreamingResponse(
            iter_bytes(),
            status_code=upstream.status_code,
            headers=headers,
            media_type=content_type,
        )
