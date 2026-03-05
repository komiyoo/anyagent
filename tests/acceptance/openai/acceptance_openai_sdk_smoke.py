from __future__ import annotations

import json
import os
import sys
import time
from typing import Any
from urllib.request import Request, urlopen
from uuid import uuid4


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


def _v1_base_url(agent_api_base_url: str) -> str:
    base = agent_api_base_url.rstrip("/")
    if base.endswith("/v1"):
        return base
    return base + "/v1"


def _http_get_json(url: str, *, agent_api_key: str, timeout_s: float = 10.0) -> Any:
    req = Request(
        url,
        headers={
            "authorization": f"Bearer {agent_api_key}",
            "accept": "application/json",
        },
        method="GET",
    )
    with urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read()
        return json.loads(raw.decode("utf-8", errors="replace"))


def _health_checks(*, agent_api_base_url: str, agent_api_key: str) -> None:
    for path in ("/healthz", "/readyz"):
        data = _http_get_json(agent_api_base_url.rstrip("/") + path, agent_api_key=agent_api_key)
        if not isinstance(data, dict) or data.get("ok") is not True:
            raise RuntimeError(f"{path} failed: {data}")


def _internal_skills_list(*, agent_api_base_url: str, agent_api_key: str) -> None:
    data = _http_get_json(
        agent_api_base_url.rstrip("/") + "/internal/skills/list?agent_id=main",
        agent_api_key=agent_api_key,
    )
    if not isinstance(data, dict) or "skills" not in data:
        raise RuntimeError(f"/internal/skills/list invalid response: {data}")


def _require_openai_sdk() -> Any:
    try:
        from openai import OpenAI
    except Exception as e:
        msg = "\n".join(
            [
                "missing dependency: openai (Python SDK)",
                "",
                "推荐运行方式（临时安装，不改 lock）：",
                "  cd apps/agent-api && uv run --with openai -s ../../tests/acceptance/openai/acceptance_openai_sdk_smoke.py",
                "",
                f"import error: {e}",
            ]
        )
        raise SystemExit(msg) from e
    return OpenAI


def _get_id(obj: Any) -> str | None:
    if isinstance(obj, dict) and isinstance(obj.get("id"), str):
        return obj["id"]
    v = getattr(obj, "id", None)
    return v if isinstance(v, str) else None


def main() -> None:
    agent_api_base_url = _env("ANYAGENT_AGENT_API_BASE_URL", "http://127.0.0.1:8787") or "http://127.0.0.1:8787"
    agent_api_key = _require_env("AGENT_API_KEY")
    model = _require_env("ANYAGENT_OPENAI_MODEL")

    _health_checks(agent_api_base_url=agent_api_base_url, agent_api_key=agent_api_key)
    _internal_skills_list(agent_api_base_url=agent_api_base_url, agent_api_key=agent_api_key)

    OpenAI = _require_openai_sdk()
    client = OpenAI(api_key=agent_api_key, base_url=_v1_base_url(agent_api_base_url))

    resp = client.responses.create(
        model=model,
        input="Say 'ok' only.",
        stream=False,
        metadata={"agent_id": "main", "session_key": f"smoke::{uuid4().hex}"},
    )
    if _get_id(resp) is None:
        raise RuntimeError("responses.create stream=false: missing id")

    saw_completed = False
    stream_start = time.time()
    with client.responses.stream(
        model=model,
        input="Count from 1 to 3.",
        metadata={"agent_id": "main", "session_key": f"smoke::{uuid4().hex}"},
    ) as stream:
        for event in stream:
            et = getattr(event, "type", None)
            if et is None and isinstance(event, dict):
                et = event.get("type")
            if et in {"response.completed", "response.done"}:
                saw_completed = True
            if time.time() - stream_start > 120:
                raise RuntimeError("responses.stream timeout (120s)")
    if not saw_completed:
        raise RuntimeError("responses.stream: missing response.completed")

    resp2 = client.responses.create(
        model=model,
        input="Fetch https://example.com/ and tell me its HTTP status code.",
        stream=False,
        metadata={"agent_id": "main", "session_key": f"smoke::{uuid4().hex}"},
        tools=[{"type": "function", "name": "core.web_fetch", "parameters": {}, "strict": True}],
        tool_choice={"type": "function", "name": "core.web_fetch"},
    )
    if _get_id(resp2) is None:
        raise RuntimeError("responses.create tool-call: missing id")

    print("ok: acceptance_openai_sdk_smoke")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(130)
