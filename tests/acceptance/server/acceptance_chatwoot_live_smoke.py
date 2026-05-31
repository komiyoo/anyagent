from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import time
from pathlib import Path

import httpx
import pytest
from openai.types.responses.response import Response
from openai.types.responses.response_function_tool_call import ResponseFunctionToolCall
from openai.types.responses.response_output_message import ResponseOutputMessage
from openai.types.responses.response_output_text import ResponseOutputText

from anyagent.server.app import create_app


ROOT = Path(__file__).resolve().parents[3]
REFERENCE_PLUGIN_ROOT = ROOT / "packages" / "anyagent" / "src" / "anyagent" / "plugins" / "builtin"

_REQUIRED_ENV = [
    "ANYAGENT_TEST_CHATWOOT_URL",
    "ANYAGENT_TEST_CHATWOOT_ACCOUNT_ID",
    "ANYAGENT_TEST_CHATWOOT_ACCESS_TOKEN",
    "ANYAGENT_TEST_CHATWOOT_WEBHOOK_SECRET",
    "ANYAGENT_TEST_CHATWOOT_CONVERSATION_ID",
]


class _ChatwootLiveProvider:
    def __init__(self) -> None:
        self.bodies: list[dict] = []

    async def create_response(
        self,
        *,
        body: dict,
        idempotency_key: str | None = None,
        timeout_s: float = 60.0,
    ) -> Response:
        _ = idempotency_key, timeout_s
        self.bodies.append(json.loads(json.dumps(body)))
        if len(self.bodies) == 1:
            return Response.model_validate(
                {
                    "id": "resp_chatwoot_live_1",
                    "object": "response",
                    "created_at": int(time.time()),
                    "model": str(body.get("model") or "gpt-4o-mini"),
                    "output": [
                        ResponseFunctionToolCall(
                            id="fc_chatwoot_live_handoff",
                            call_id="call_chatwoot_live_handoff",
                            name="gateway.handoff",
                            arguments=json.dumps(
                                {
                                    "reason": "customer_request",
                                    "suggested_team": "7",
                                    "summary": "Customer asked for a human.",
                                },
                                ensure_ascii=False,
                            ),
                            type="function_call",
                        ).model_dump(exclude_none=True, by_alias=True)
                    ],
                    "parallel_tool_calls": False,
                    "tool_choice": "auto",
                    "tools": list(body.get("tools") or []),
                    "status": "completed",
                }
            )
        return Response.model_validate(
            {
                "id": "resp_chatwoot_live_2",
                "object": "response",
                "created_at": int(time.time()),
                "model": str(body.get("model") or "gpt-4o-mini"),
                "output": [
                    ResponseOutputMessage(
                        id="msg_chatwoot_live_reply",
                        type="message",
                        role="assistant",
                        status="completed",
                        content=[ResponseOutputText(type="output_text", text="Hello from anyagent", annotations=[])],
                    ).model_dump(exclude_none=True, by_alias=True)
                ],
                "parallel_tool_calls": False,
                "tool_choice": "auto",
                "tools": list(body.get("tools") or []),
                "status": "completed",
            }
        )


def _write_workspace(root: Path) -> None:
    agent_dir = root / ".anyagent" / "agents" / "main"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "AGENTS.md").write_text("You are main.\n", encoding="utf-8")
    (agent_dir / "agent.yaml").write_text(
        "\n".join(
            [
                "exposed: true",
                "tools:",
                "  requested_tool_names: []",
                "skills:",
                "  default_selected: []",
                "sandbox:",
                "  mode: disabled",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_chatwoot_live_smoke(tmp_path: Path, monkeypatch) -> None:
    missing = [name for name in _REQUIRED_ENV if not os.getenv(name)]
    if missing:
        pytest.skip(f"missing live Chatwoot env: {', '.join(missing)}")
    asyncio.run(_run_chatwoot_live_smoke(tmp_path=tmp_path, monkeypatch=monkeypatch))


async def _run_chatwoot_live_smoke(*, tmp_path: Path, monkeypatch) -> None:
    _write_workspace(tmp_path)
    chatwoot_url = os.environ["ANYAGENT_TEST_CHATWOOT_URL"].rstrip("/")
    account_id = os.environ["ANYAGENT_TEST_CHATWOOT_ACCOUNT_ID"]
    access_token = os.environ["ANYAGENT_TEST_CHATWOOT_ACCESS_TOKEN"]
    webhook_secret = os.environ["ANYAGENT_TEST_CHATWOOT_WEBHOOK_SECRET"]
    conversation_id = os.environ["ANYAGENT_TEST_CHATWOOT_CONVERSATION_ID"]

    monkeypatch.setenv("ANYAGENT_CHATWOOT_URL", chatwoot_url)
    monkeypatch.setenv("ANYAGENT_CHATWOOT_ACCOUNT_ID", account_id)
    monkeypatch.setenv("ANYAGENT_CHATWOOT_ACCESS_TOKEN", access_token)
    monkeypatch.setenv("ANYAGENT_CHATWOOT_WEBHOOK_SECRET", webhook_secret)
    monkeypatch.setenv("ANYAGENT_CHATWOOT_CREDENTIAL_KIND", "webhook_secret")
    monkeypatch.setattr(
        "anyagent.server.routes.responses.get_default_model_provider",
        lambda: _ChatwootLiveProvider(),
    )

    app = create_app(
        workspace_dir=tmp_path,
        api_key="user-key",
        admin_api_key="admin-key",
        plugin_roots=[REFERENCE_PLUGIN_ROOT],
    )

    before = await _fetch_conversation_details(
        base_url=chatwoot_url,
        account_id=account_id,
        conversation_id=conversation_id,
        access_token=access_token,
    )
    before_ids = {str(item.get("id")) for item in before.get("messages", []) if item.get("id") is not None}

    payload = {
        "event": "message_created",
        "timestamp": 1717000000,
        "account": {"id": int(account_id)},
        "conversation": {"id": int(conversation_id)},
        "message": {"content": "I need to talk to a person"},
    }
    raw_body = json.dumps(payload).encode("utf-8")
    signature = hmac.new(
        webhook_secret.encode("utf-8"),
        f"{payload['timestamp']}.{raw_body.decode('utf-8')}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as local_http:
        response = await local_http.post(
            "/gateway/chatwoot/webhook",
            headers={"x-chatwoot-signature": signature, "x-chatwoot-timestamp": str(payload["timestamp"])},
            content=raw_body,
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["processed"] is True
        assert result["reply_sent"] is True
        assert result["handoff_triggered"] is True
        assert result["handoff_executed"] is True

    details = await _wait_for_chatwoot_side_effects(
        base_url=chatwoot_url,
        account_id=account_id,
        conversation_id=conversation_id,
        access_token=access_token,
        before_ids=before_ids,
    )
    assert str(details.get("status")) == "open"

    messages = details.get("messages", [])
    contents = [str(item.get("content") or "") for item in messages if isinstance(item, dict)]
    assert any("Hello from anyagent" in content for content in contents)
    assert any("[AI 摘要] Customer asked for a human." in content for content in contents)


async def _fetch_conversation_details(
    *,
    base_url: str,
    account_id: str,
    conversation_id: str,
    access_token: str,
) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{base_url}/api/v1/accounts/{account_id}/conversations/{conversation_id}",
            headers={"api_access_token": access_token, "Accept": "application/json"},
        )
        response.raise_for_status()
        return response.json()


async def _wait_for_chatwoot_side_effects(
    *,
    base_url: str,
    account_id: str,
    conversation_id: str,
    access_token: str,
    before_ids: set[str],
    timeout_s: float = 20.0,
) -> dict:
    deadline = time.time() + timeout_s
    last_payload: dict | None = None
    while time.time() < deadline:
        details = await _fetch_conversation_details(
            base_url=base_url,
            account_id=account_id,
            conversation_id=conversation_id,
            access_token=access_token,
        )
        last_payload = details
        messages = details.get("messages", [])
        new_messages = [
            item
            for item in messages
            if isinstance(item, dict) and str(item.get("id")) not in before_ids
        ]
        contents = [str(item.get("content") or "") for item in new_messages]
        if (
            str(details.get("status")) == "open"
            and any("Hello from anyagent" in content for content in contents)
            and any("[AI 摘要] Customer asked for a human." in content for content in contents)
        ):
            return details
        await asyncio.sleep(1.0)
    raise AssertionError(f"chatwoot live side effects not observed in time: {last_payload}")
