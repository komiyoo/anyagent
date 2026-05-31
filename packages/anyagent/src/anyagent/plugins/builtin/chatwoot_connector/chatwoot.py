"""
Chatwoot Connector — Inbound Channel Connector 参考实现。

功能：
- 接收 Chatwoot Agent Bot webhook（message_created 等事件）
- HMAC-SHA256 签名验证
- 平台会话映射为 anyagent session_key
- agent 回复通过 Chatwoot API 回写到会话
- 转人工信号处理（toggle_status → open）
- 会话生命周期事件注入

参考：
- Chatwoot Agent Bot API: https://developers.chatwoot.com/api-reference/account-agentbots/create-an-agent-bot
- Chatwoot webhook 签名: https://github.com/chatwoot/chatwoot/blob/develop/lib/webhooks/trigger.rb
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any

import httpx

from anyagent.gateway.connector_contracts import (
    ConnectorWebhookAuth,
    ConnectorOutboundDelivery,
    ConnectorHandoff,
    HandoffMetadata,
    HandoffReason,
    HandoffResult,
    OutboundDeliveryError,
    OutboundMessageResult,
    PlatformConversationEvent,
    PlatformConversationEventType,
    WebhookAuthError,
    WebhookAuthSuccess,
    chatwoot_session_key,
)

_LOGGER = logging.getLogger(__name__)

# ── Chatwoot webhook 签名验证 ────────────────────────────────────


class ChatwootWebhookAuth(ConnectorWebhookAuth):
    """
    Chatwoot HMAC-SHA256 签名验证。

    Chatwoot 签名算法：
        signature = "sha256=" + HMAC-SHA256(secret, "{timestamp}.{body}").hexdigest

    签名在请求头 X-Chatwoot-Signature 中，时间戳在请求头 X-Chatwoot-Timestamp 中。
    """

    SIGNATURE_HEADER = "x-chatwoot-signature"
    TIMESTAMP_HEADER = "x-chatwoot-timestamp"

    async def verify(
        self,
        headers: dict[str, str],
        raw_body: bytes,
        secret: str,
    ) -> WebhookAuthSuccess:
        # 1. 提取签名（Chatwoot 格式: "sha256=<hex_digest>"）
        raw_signature = headers.get(self.SIGNATURE_HEADER, "")
        if not raw_signature:
            raise WebhookAuthError("missing X-Chatwoot-Signature header", status_code=401)
        signature = raw_signature.removeprefix("sha256=")

        # 2. 提取时间戳（来自 X-Chatwoot-Timestamp 请求头）
        timestamp = headers.get(self.TIMESTAMP_HEADER, "")
        if not timestamp:
            raise WebhookAuthError("missing X-Chatwoot-Timestamp header", status_code=401)

        # 3. HMAC-SHA256 计算（hexdigest，与 Chatwoot Ruby hexdigest 一致）
        payload = f"{timestamp}.{raw_body.decode('utf-8')}"
        computed = hmac.new(
            secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        # 4. 常量时间比较
        if not hmac.compare_digest(computed, signature):
            raise WebhookAuthError("HMAC signature mismatch", status_code=403)

        # 5. 解析 JSON body（提取平台上下文）
        try:
            body_json = json.loads(raw_body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise WebhookAuthError(f"invalid JSON body: {exc}", status_code=400) from exc

        # 6. 提取平台上下文
        account_id = str(body_json.get("account", {}).get("id", ""))
        conversation_id = str(body_json.get("conversation", {}).get("id", ""))

        return WebhookAuthSuccess(
            verified=True,
            platform="chatwoot",
            account_id=account_id,
            metadata={
                "conversation_id": conversation_id,
                "event": body_json.get("event", ""),
                "timestamp": timestamp,
            },
        )


# ── Chatwoot outbound message delivery ────────────────────────────


class ChatwootOutboundDelivery(ConnectorOutboundDelivery):
    """
    Chatwoot Agent Bot API 出站消息发送。

    使用 Agent Bot access_token 鉴权，通过 Chatwoot REST API
    将消息发送到指定会话。

    API:
        POST /api/v1/accounts/{account_id}/conversations/{conversation_id}/messages
    """

    def __init__(
        self,
        *,
        chatwoot_url: str,
        account_id: str | int,
        access_token: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = str(chatwoot_url).rstrip("/")
        self._account_id = str(account_id)
        self._access_token = access_token
        self._client = http_client

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "api_access_token": self._access_token,
            },
            timeout=httpx.Timeout(30.0),
        )

    async def send_message(
        self,
        platform_conversation_id: str,
        content: str,
        *,
        content_type: str = "text",
        metadata: dict[str, Any] | None = None,
    ) -> OutboundMessageResult:
        client = await self._get_client()
        url = f"/api/v1/accounts/{self._account_id}/conversations/{platform_conversation_id}/messages"

        payload: dict[str, Any] = {
            "content": content,
            "message_type": "outgoing",
            "content_type": "text" if content_type == "text" else content_type,
        }

        if metadata:
            payload["private"] = bool(metadata.get("private", False))

        try:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            return OutboundMessageResult(
                ok=True,
                platform_message_id=str(data.get("id", "")),
                metadata={"status_code": resp.status_code},
            )
        except httpx.HTTPStatusError as exc:
            raise OutboundDeliveryError(
                f"Chatwoot API error: {exc.response.status_code} {exc.response.text}",
                status_code=exc.response.status_code,
                retryable=exc.response.status_code >= 500 or exc.response.status_code == 429,
            ) from exc
        except httpx.RequestError as exc:
            raise OutboundDeliveryError(
                f"Chatwoot API request failed: {exc}",
                status_code=502,
                retryable=True,
            ) from exc
        finally:
            if self._client is None:
                await client.aclose()

    async def send_private_note(
        self,
        platform_conversation_id: str,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> OutboundMessageResult:
        return await self.send_message(
            platform_conversation_id=platform_conversation_id,
            content=content,
            content_type="text",
            metadata={"private": True, **(metadata or {})},
        )


# ── Chatwoot handoff 处理 ─────────────────────────────────────────


class ChatwootHandoff(ConnectorHandoff):
    """
    Chatwoot 转人工处理。

    将 Chatwoot 会话状态切换为 open（移除 bot assignment），
    并可选择 assign 到特定团队 / 坐席。

    API:
        POST /api/v1/accounts/{account_id}/conversations/{conversation_id}/toggle_status
        POST /api/v1/accounts/{account_id}/conversations/{conversation_id}/assignments
    """

    def __init__(
        self,
        *,
        chatwoot_url: str,
        account_id: str | int,
        access_token: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = str(chatwoot_url).rstrip("/")
        self._account_id = str(account_id)
        self._access_token = access_token
        self._client = http_client

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "api_access_token": self._access_token,
            },
            timeout=httpx.Timeout(30.0),
        )

    async def execute_handoff(
        self,
        platform_conversation_id: str,
        reason: HandoffReason,
        *,
        metadata: HandoffMetadata | None = None,
    ) -> HandoffResult:
        client = await self._get_client()
        results: dict[str, Any] = {}

        try:
            # Step 1: 切换会话状态为 open
            toggle_url = (
                f"/api/v1/accounts/{self._account_id}/conversations/"
                f"{platform_conversation_id}/toggle_status"
            )
            resp = await client.post(toggle_url, json={"status": "open"})
            resp.raise_for_status()
            results["toggled"] = True

            # Step 2: 可选 assign 到指定 team/agent
            if metadata:
                assign_url = (
                    f"/api/v1/accounts/{self._account_id}/conversations/"
                    f"{platform_conversation_id}/assignments"
                )
                assign_payload: dict[str, Any] = {}
                if metadata.suggested_team:
                    assign_payload["team_id"] = int(metadata.suggested_team)
                if metadata.suggested_agent:
                    assign_payload["assignee_id"] = int(metadata.suggested_agent)

                if assign_payload:
                    try:
                        resp = await client.post(assign_url, json=assign_payload)
                        resp.raise_for_status()
                        results["assigned"] = True
                    except httpx.HTTPStatusError:
                        _LOGGER.warning(
                            "Chatwoot assign failed: conversation_id=%s", platform_conversation_id
                        )
                        results["assigned"] = False

            # Step 3: 如果有 AI 生成的摘要，作为 private note 发送
            if metadata and metadata.summary:
                note_url = (
                    f"/api/v1/accounts/{self._account_id}/conversations/"
                    f"{platform_conversation_id}/messages"
                )
                note_payload = {
                    "content": f"[AI 摘要] {metadata.summary}",
                    "message_type": "outgoing",
                    "private": True,
                }
                try:
                    resp = await client.post(note_url, json=note_payload)
                    resp.raise_for_status()
                    results["summary_sent"] = True
                except httpx.HTTPStatusError:
                    _LOGGER.warning(
                        "Chatwoot note send failed: conversation_id=%s", platform_conversation_id
                    )
                    results["summary_sent"] = False

            return HandoffResult(
                ok=True,
                reason=f"Handoff executed for reason: {reason.value}",
                metadata=results,
            )

        except httpx.HTTPStatusError as exc:
            _LOGGER.error("Chatwoot handoff failed: %s", exc)
            return HandoffResult(
                ok=False,
                reason=f"Chatwoot API error: {exc.response.status_code}",
                metadata=results,
            )
        except httpx.RequestError as exc:
            _LOGGER.error("Chatwoot handoff request failed: %s", exc)
            return HandoffResult(
                ok=False,
                reason=f"Request error: {exc}",
                metadata=results,
            )
        finally:
            if self._client is None:
                await client.aclose()


# ── 平台会话生命周期事件构建 ──────────────────────────────────────


_CHATWOOT_EVENT_TYPE_MAP: dict[str, PlatformConversationEventType] = {
    "message_created": PlatformConversationEventType.USER_MESSAGE,
    "conversation_status_changed": PlatformConversationEventType.CUSTOM,
    "conversation_resolved": PlatformConversationEventType.RESOLVED,
    "conversation_reopened": PlatformConversationEventType.REOPENED,
    "conversation_closed": PlatformConversationEventType.CLOSED,
    "conversation_snoozed": PlatformConversationEventType.SNOOZED,
    "assigned_to_human": PlatformConversationEventType.ASSIGNED_TO_HUMAN,
    "assigned_to_bot": PlatformConversationEventType.ASSIGNED_TO_BOT,
}


def build_platform_event_from_webhook(
    *,
    account_id: str | int,
    webhook_body: dict[str, Any],
) -> PlatformConversationEvent:
    """
    从 Chatwoot webhook 请求体构建 PlatformConversationEvent。

    Args:
        account_id: Chatwoot account ID。
        webhook_body: Chatwoot webhook 请求体 JSON。
    """
    conversation = webhook_body.get("conversation", {})
    conversation_id = str(conversation.get("id", "") or webhook_body.get("id", ""))
    event_name = str(webhook_body.get("event", ""))

    session_key = chatwoot_session_key(account_id=account_id, conversation_id=conversation_id)
    event_type = _CHATWOOT_EVENT_TYPE_MAP.get(event_name, PlatformConversationEventType.CUSTOM)

    return PlatformConversationEvent(
        session_key=session_key,
        event_type=event_type,
        platform="chatwoot",
        platform_conversation_id=conversation_id,
        metadata={
            "chatwoot_event": event_name,
            "account_id": str(account_id),
            "webhook_timestamp": webhook_body.get("timestamp") or webhook_body.get("created_at"),
        },
    )
