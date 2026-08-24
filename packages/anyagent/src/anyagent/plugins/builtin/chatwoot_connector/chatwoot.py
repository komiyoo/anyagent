"""
Chatwoot Connector — Inbound Channel Connector 参考实现。

功能：
- 接收 Chatwoot Agent Bot webhook（message_created 等事件）
- HMAC-SHA256 签名验证
- 平台会话映射为 anyagent session_key
- agent 回复通过 Chatwoot API 回写到会话
- 会话状态变更（handoff → open、bot 回复后 pending → open；默认开启，经 status_changes_enabled 显式关闭）
- 已分配真人坐席时跳过 bot 回复（assignee_type=User；不把 status=open 当 handoff 信号）
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

    默认 `status_changes_enabled=True`：handoff 将会话切换为 open，且
    open_conversation 在 bot 回复后将 pending 会话置为 open。
    显式传 False 时跳过所有 toggle_status 调用（connector 不以任何方式修改
    Chatwoot 会话状态），仅保留 assignment 与 AI 摘要 private note。

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
        status_changes_enabled: bool = True,
    ) -> None:
        self._base_url = str(chatwoot_url).rstrip("/")
        self._account_id = str(account_id)
        self._access_token = access_token
        self._client = http_client
        self._status_changes_enabled = status_changes_enabled

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
            # Step 1: 切换会话状态为 open（status_changes_enabled=False 时跳过，
            # connector 不发起任何 toggle_status 类请求）
            if self._status_changes_enabled:
                toggle_url = (
                    f"/api/v1/accounts/{self._account_id}/conversations/"
                    f"{platform_conversation_id}/toggle_status"
                )
                resp = await client.post(toggle_url, json={"status": "open"})
                resp.raise_for_status()
                results["toggled"] = True
            else:
                results["toggled"] = False
                results["status_change_skipped"] = True
                _LOGGER.info(
                    "Chatwoot status change skipped (disabled): conversation_id=%s",
                    platform_conversation_id,
                )

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

    async def open_conversation(self, platform_conversation_id: str) -> bool:
        """将会话状态置为 open（bot 回复后调用，使其保持在 Open 列表）。

        只允许切到 open，从不 resolve / snooze。与 execute_handoff 不同：
        不做 assignment / 摘要 note。受 status_changes_enabled 控制，关闭时
        为 no-op。失败不抛异常（回复已送达，状态切换失败不应影响主流程）。
        """
        if not self._status_changes_enabled:
            return False

        client = await self._get_client()
        try:
            resp = await client.post(
                f"/api/v1/accounts/{self._account_id}/conversations/"
                f"{platform_conversation_id}/toggle_status",
                json={"status": "open"},
            )
            resp.raise_for_status()
            return True
        except httpx.HTTPError as exc:
            _LOGGER.warning(
                "Chatwoot open conversation failed: conversation_id=%s error=%s",
                platform_conversation_id,
                exc,
            )
            return False
        finally:
            if self._client is None:
                await client.aclose()

    async def get_conversation(self, platform_conversation_id: str) -> dict[str, Any] | None:
        """读取会话当前状态（用于发信前再核 assignee）。

        无 access_token 时不发请求，返回 None。失败不抛异常。
        """
        conversation_id = str(platform_conversation_id).strip()
        if not self._access_token or not conversation_id:
            return None

        client = await self._get_client()
        try:
            resp = await client.get(
                f"/api/v1/accounts/{self._account_id}/conversations/{conversation_id}"
            )
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict):
                return None
            payload = data.get("payload", data)
            return payload if isinstance(payload, dict) else None
        except httpx.HTTPError as exc:
            _LOGGER.warning(
                "Chatwoot get conversation failed: conversation_id=%s error=%s",
                conversation_id,
                exc,
            )
            return None
        finally:
            if self._client is None:
                await client.aclose()


# ── 平台会话生命周期事件构建 ──────────────────────────────────────


_CHATWOOT_EVENT_TYPE_MAP: dict[str, PlatformConversationEventType] = {
    "message_created": PlatformConversationEventType.USER_MESSAGE,
    "webwidget_triggered": PlatformConversationEventType.CUSTOM,
    "widget_triggered": PlatformConversationEventType.CUSTOM,
    "conversation_status_changed": PlatformConversationEventType.CUSTOM,
    "conversation_resolved": PlatformConversationEventType.RESOLVED,
    "conversation_reopened": PlatformConversationEventType.REOPENED,
    "conversation_closed": PlatformConversationEventType.CLOSED,
    "conversation_snoozed": PlatformConversationEventType.SNOOZED,
    "assigned_to_human": PlatformConversationEventType.ASSIGNED_TO_HUMAN,
    "assigned_to_bot": PlatformConversationEventType.ASSIGNED_TO_BOT,
}


def extract_chatwoot_page_context(webhook_body: dict[str, Any]) -> dict[str, str]:
    """Extract page context propagated by Chatwoot widget/webhook payloads."""
    event_info = _dict_at(webhook_body, "event_info")
    custom_attributes = _chatwoot_custom_attributes(webhook_body)

    context: dict[str, str] = {}
    _set_str(context, "referer", event_info.get("referer") or custom_attributes.get("lt_entry_referrer"))
    _set_str(context, "entry_url", custom_attributes.get("lt_entry_url"))
    _set_str(context, "entry_path", custom_attributes.get("lt_entry_path"))
    _set_str(context, "entry_title", custom_attributes.get("lt_entry_title"))
    _set_str(context, "entry_locale", custom_attributes.get("lt_entry_locale"))
    _set_str(context, "widget_language", event_info.get("widget_language"))
    _set_str(context, "browser_language", event_info.get("browser_language"))
    return context


def _chatwoot_custom_attributes(webhook_body: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for path in (
        ("conversation", "custom_attributes"),
        ("contact", "custom_attributes"),
        ("sender", "custom_attributes"),
        ("meta", "sender", "custom_attributes"),
    ):
        current: Any = webhook_body
        for key in path:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(key)
        if isinstance(current, dict):
            merged.update(current)
    return merged


def _dict_at(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def _set_str(target: dict[str, str], key: str, value: Any) -> None:
    if isinstance(value, str) and value.strip():
        target[key] = value.strip()


_HUMAN_ASSIGNEE_TYPE = "user"
_BOT_ASSIGNEE_TYPES = {"agentbot", "captain"}
_HUMAN_ASSIGNEE_ROLES = {"agent", "administrator"}


def _normalize_assignee_token(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().lower().replace("_", "").replace("-", "")


def _source_assigned_to_human(source: dict[str, Any]) -> bool:
    meta = source.get("meta")
    meta_dict = meta if isinstance(meta, dict) else {}
    assignee_type = meta_dict.get("assignee_type", source.get("assignee_type"))
    if _normalize_assignee_token(assignee_type) == _HUMAN_ASSIGNEE_TYPE:
        return True

    assignee = meta_dict.get("assignee", source.get("assignee"))
    if not isinstance(assignee, dict) or not assignee:
        return False
    token = _normalize_assignee_token(assignee.get("type"))
    if token in _BOT_ASSIGNEE_TYPES:
        return False
    if token == _HUMAN_ASSIGNEE_TYPE:
        return True
    role = assignee.get("role")
    if isinstance(role, str) and role.strip().lower() in _HUMAN_ASSIGNEE_ROLES:
        return True
    email = assignee.get("email")
    return isinstance(email, str) and bool(email.strip())


def conversation_assigned_to_human(payload: dict[str, Any] | None) -> bool:
    """Webhook body 或 GET conversation 载荷是否已分配给真人坐席。

    本仓策略会把 bot 回复后的会话也改成 open，因此不能用 status=open 判断。
    依据是 meta.assignee_type / assignee.type == user，或坐席带 agent/administrator role。
    """
    if not isinstance(payload, dict):
        return False
    conversation = payload.get("conversation")
    if isinstance(conversation, dict) and _source_assigned_to_human(conversation):
        return True
    return _source_assigned_to_human(payload)


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
    metadata: dict[str, Any] = {
        "chatwoot_event": event_name,
        "account_id": str(account_id),
        "webhook_timestamp": webhook_body.get("timestamp") or webhook_body.get("created_at"),
    }
    page_context = extract_chatwoot_page_context(webhook_body)
    if page_context:
        metadata["chatwoot_page_context"] = page_context

    return PlatformConversationEvent(
        session_key=session_key,
        event_type=event_type,
        platform="chatwoot",
        platform_conversation_id=conversation_id,
        metadata=metadata,
    )
