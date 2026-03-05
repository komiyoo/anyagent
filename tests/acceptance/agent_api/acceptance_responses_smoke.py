from __future__ import annotations

import json
import os
import sys
import time
from typing import Any
from uuid import uuid4

import httpx


def _env(name: str, default: str | None = None) -> str | None:
    v = os.getenv(name)
    if v is None:
        return default
    v = v.strip()
    return v or default


def _require_env(name: str) -> str:
    v = _env(name)
    if not v:
        raise SystemExit(f"missing required env: {name}")
    return v


def _headers(agent_api_key: str) -> dict[str, str]:
    return {"authorization": f"Bearer {agent_api_key}", "content-type": "application/json"}


async def _health_check(client: httpx.AsyncClient, base_url: str, headers: dict[str, str]) -> None:
    for path in ("/healthz", "/readyz"):
        r = await client.get(base_url + path, headers=headers, timeout=10.0)
        if r.status_code != 200:
            raise RuntimeError(f"{path} failed: {r.status_code} {r.text}")


async def _internal_skills_list(client: httpx.AsyncClient, base_url: str, headers: dict[str, str]) -> None:
    r = await client.get(base_url + "/internal/skills/list?agent_id=main", headers=headers, timeout=10.0)
    if r.status_code != 200:
        raise RuntimeError(f"/internal/skills/list failed: {r.status_code} {r.text}")
    data = r.json()
    if not isinstance(data, dict) or "skills" not in data:
        raise RuntimeError("/internal/skills/list: invalid response")


async def _responses_non_stream(
    client: httpx.AsyncClient,
    base_url: str,
    headers: dict[str, str],
    model: str,
) -> None:
    body: dict[str, Any] = {
        "model": model,
        "input": "Say 'ok' only.",
        "stream": False,
        "metadata": {"agent_id": "main", "session_key": f"smoke::{uuid4().hex}"},
    }
    r = await client.post(base_url + "/v1/responses", headers=headers, json=body, timeout=60.0)
    if r.status_code != 200:
        raise RuntimeError(f"/v1/responses stream=false failed: {r.status_code} {r.text}")
    data = r.json()
    if not isinstance(data, dict) or not isinstance(data.get("id"), str):
        raise RuntimeError("/v1/responses stream=false: invalid response")


async def _responses_stream_sse(
    client: httpx.AsyncClient,
    base_url: str,
    headers: dict[str, str],
    model: str,
) -> None:
    body: dict[str, Any] = {
        "model": model,
        "input": "Count from 1 to 3.",
        "stream": True,
        "metadata": {"agent_id": "main", "session_key": f"smoke::{uuid4().hex}"},
    }

    saw_completed = False
    saw_done = False
    start = time.time()
    cur_event: str | None = None

    async with client.stream("POST", base_url + "/v1/responses", headers=headers, json=body, timeout=None) as r:
        if r.status_code != 200:
            text = (await r.aread()).decode("utf-8", errors="replace")
            raise RuntimeError(f"/v1/responses stream=true failed: {r.status_code} {text}")

        async for line in r.aiter_lines():
            if line.startswith("event:"):
                cur_event = line[len("event:") :].strip() or None
                if cur_event in {"response.completed", "response.done"}:
                    saw_completed = True
            if line.startswith("data:"):
                data = line[len("data:") :].lstrip()
                if data.strip() == "[DONE]":
                    saw_done = True
                    break
                if not data.strip():
                    continue

            if time.time() - start > 120:
                raise RuntimeError("/v1/responses stream=true timeout (120s)")

    if not saw_done:
        raise RuntimeError("/v1/responses stream=true: missing [DONE]")
    if not saw_completed:
        raise RuntimeError("/v1/responses stream=true: missing response.completed")


async def _responses_tool_call(
    client: httpx.AsyncClient,
    base_url: str,
    headers: dict[str, str],
    model: str,
) -> None:
    # Make core.web_fetch visible + force tool_choice to reduce flakiness.
    body: dict[str, Any] = {
        "model": model,
        "input": "Fetch https://example.com/ and tell me its HTTP status code.",
        "stream": False,
        "metadata": {"agent_id": "main", "session_key": f"smoke::{uuid4().hex}"},
        # schema should come from Tool Runtime manifest; caller only needs to request visibility by name
        "tools": [{"type": "function", "name": "core.web_fetch", "parameters": {}, "strict": True}],
        "tool_choice": {"type": "function", "name": "core.web_fetch"},
    }
    r = await client.post(base_url + "/v1/responses", headers=headers, json=body, timeout=120.0)
    if r.status_code != 200:
        raise RuntimeError(f"/v1/responses tool-call failed: {r.status_code} {r.text}")
    data = r.json()
    if not isinstance(data, dict) or not isinstance(data.get("id"), str):
        raise RuntimeError("/v1/responses tool-call: invalid response")


async def main() -> None:
    agent_api_base_url = _env("ANYAGENT_AGENT_API_BASE_URL", "http://127.0.0.1:8787")
    agent_api_key = _require_env("AGENT_API_KEY")
    model = _require_env("ANYAGENT_OPENAI_MODEL")

    headers = _headers(agent_api_key)
    async with httpx.AsyncClient() as client:
        await _health_check(client, agent_api_base_url, headers)
        await _internal_skills_list(client, agent_api_base_url, headers)
        await _responses_non_stream(client, agent_api_base_url, headers, model)
        await _responses_stream_sse(client, agent_api_base_url, headers, model)
        await _responses_tool_call(client, agent_api_base_url, headers, model)

    print("ok: acceptance_responses_smoke")


if __name__ == "__main__":
    try:
        import asyncio

        asyncio.run(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
