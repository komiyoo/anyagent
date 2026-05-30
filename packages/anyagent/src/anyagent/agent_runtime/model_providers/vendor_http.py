from __future__ import annotations

from typing import Any

import httpx

from .base import ModelProviderTransportError, ModelProviderUpstreamError


async def post_json_normalized(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    url_path: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_s: float,
    upstream_name: str,
    request_id_header: str = "request-id",
) -> dict[str, Any]:
    try:
        response = await client.post(
            base_url.rstrip("/") + "/" + url_path.lstrip("/"),
            headers=headers,
            json=payload,
            timeout=timeout_s,
        )
    except httpx.TimeoutException as e:
        raise ModelProviderTransportError(str(e)) from e
    except httpx.RequestError as e:
        raise ModelProviderTransportError(str(e)) from e

    if response.status_code >= 400:
        body_obj: object | None
        try:
            body_obj = response.json()
        except Exception:  # noqa: BLE001
            body_obj = {"error": {"message": response.text}}
        raise ModelProviderUpstreamError(
            status_code=response.status_code,
            body=body_obj,
            raw=response.content,
            request_id=response.headers.get(request_id_header),
            message=f"{upstream_name} upstream error",
        )

    try:
        data = response.json()
    except Exception as e:  # noqa: BLE001
        raise ModelProviderTransportError(f"unexpected {upstream_name} response (invalid json)") from e
    if not isinstance(data, dict):
        raise ModelProviderTransportError(f"unexpected {upstream_name} response (not an object)")
    return data
