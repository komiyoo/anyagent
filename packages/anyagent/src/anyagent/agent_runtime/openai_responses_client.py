from __future__ import annotations

from typing import Any

import httpx

from .sse import extract_completed_response, parse_sse_events


class OpenAIResponsesClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        http: httpx.AsyncClient | None = None,
        user_agent: str = "AnyAgent/0",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._http = http
        self._user_agent = user_agent

    def _headers(self, *, idempotency_key: str | None) -> dict[str, str]:
        headers: dict[str, str] = {
            "authorization": f"Bearer {self._api_key}",
            "content-type": "application/json",
            "user-agent": self._user_agent,
        }
        if idempotency_key:
            headers["idempotency-key"] = idempotency_key
        return headers

    async def create_json(
        self,
        *,
        body: dict[str, Any],
        idempotency_key: str | None = None,
        timeout_s: float = 60.0,
    ) -> tuple[int, dict[str, Any]]:
        url = f"{self._base_url}/responses"
        if self._http is None:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                r = await client.post(url, headers=self._headers(idempotency_key=idempotency_key), json=body)
        else:
            r = await self._http.post(
                url, headers=self._headers(idempotency_key=idempotency_key), json=body, timeout=timeout_s
            )
        try:
            data: Any = r.json()
        except Exception:  # noqa: BLE001
            data = {"error": {"message": r.text, "type": "upstream_error"}}
        return r.status_code, data if isinstance(data, dict) else {"error": {"message": "invalid_json", "type": "upstream_error"}}

    async def create_sse_buffer(
        self,
        *,
        body: dict[str, Any],
        idempotency_key: str | None = None,
        timeout_s: float | None = None,
    ) -> tuple[int, list[tuple[str | None, str]], dict[str, Any] | None, str]:
        """
        v0：为了能在 AgentRuntime 里做 tool loop，我们需要读完整 SSE 并提取 response.completed。
        返回 (status_code, events, completed_response, raw_text)。
        """
        url = f"{self._base_url}/responses"
        if self._http is None:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                async with client.stream(
                    "POST", url, headers=self._headers(idempotency_key=idempotency_key), json=body
                ) as r:
                    raw = await r.aread()
                    text = raw.decode("utf-8", errors="replace")
                    events = parse_sse_events(text)
                    completed = extract_completed_response(events)
                    return r.status_code, events, completed, text

        async with self._http.stream(
            "POST", url, headers=self._headers(idempotency_key=idempotency_key), json=body, timeout=timeout_s
        ) as r:
            raw = await r.aread()
            text = raw.decode("utf-8", errors="replace")
            events = parse_sse_events(text)
            completed = extract_completed_response(events)
            return r.status_code, events, completed, text

