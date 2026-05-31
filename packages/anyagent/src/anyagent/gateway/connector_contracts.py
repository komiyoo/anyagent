"""
Inbound Channel Connector 通用契约（Gateway 层）。

定义 platform connector 必须实现的接口：
- ConnectorWebhookAuth：入站 webhook 签名验证
- ConnectorOutboundDelivery：出站消息回传
- ConnectorHandoff：人工接管信号处理

以及框架级通用模型：
- PlatformConversationEvent：平台会话生命周期事件
- HandoffOutputItem：agent 响应中的转人工信号

所有契约均为 platform-agnostic，不耦合任何特定平台（Chatwoot / Intercom / Zendesk / Telegram bot 等）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


# ── Webhook 签名验证 ──────────────────────────────────────────────


class WebhookAuthError(Exception):
    """入站 webhook 验签失败。"""

    def __init__(self, message: str, *, status_code: int = 401) -> None:
        super().__init__(message)
        self.status_code = status_code


class WebhookAuthSuccess(BaseModel):
    """验签通过后返回的上下文信息（connector 可在 handler 中使用）。"""

    model_config = ConfigDict(extra="allow")

    verified: bool = True
    platform: str | None = None
    account_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConnectorWebhookAuth(ABC):
    """
    Connector webhook 签名验证基类。

    每个 platform connector 应继承并实现 `verify()`。
    框架在路由到 connector handler 前自动执行验签，失败返回 401/403。

    密钥来源应走 Credential Vault（`credential_id` 引用），不硬编码。

    示例：
        Chatwoot: HMAC-SHA256(secret, f"{timestamp}.{body}")
        Telegram: compare token hash
        Lark:     AES decrypt + verify
    """

    @abstractmethod
    async def verify(
        self,
        headers: dict[str, str],
        raw_body: bytes,
        secret: str,
    ) -> WebhookAuthSuccess:
        """
        验证入站 webhook 请求签名。

        Args:
            headers: HTTP 请求头。
            raw_body: 原始请求体（bytes，不要提前 decode 以避免编码差异）。
            secret: 从 Credential Vault 解析出的签名密钥。

        Returns:
            WebhookAuthSuccess 表示验证通过。

        Raises:
            WebhookAuthError: 验签失败，框架返回 401/403。
        """
        ...


# ── 出站消息回传 ──────────────────────────────────────────────────


class OutboundDeliveryError(Exception):
    """出站消息发送失败。"""

    def __init__(self, message: str, *, status_code: int = 502, retryable: bool = True) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class OutboundMessageResult(BaseModel):
    """出站消息发送结果。"""

    ok: bool
    platform_message_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConnectorOutboundDelivery(ABC):
    """
    Outbound message delivery 基类。

    connector 把 agent 的回复内容通过平台 API 写回对应会话。
    鉴权 token 走 Credential Vault。

    示例：
        Chatwoot:  POST /api/v1/accounts/{id}/conversations/{cid}/messages
        Telegram:  sendMessage
        Intercom:  POST /conversations/{id}/reply
    """

    @abstractmethod
    async def send_message(
        self,
        platform_conversation_id: str,
        content: str,
        *,
        content_type: str = "text",
        metadata: dict[str, Any] | None = None,
    ) -> OutboundMessageResult:
        """
        将消息内容发送到平台会话。

        Args:
            platform_conversation_id: 平台侧会话 ID。
            content: 消息内容。
            content_type: 内容类型（"text" / "markdown" / "html" 等）。
            metadata: 附加元数据（如引用消息、附件等）。

        Returns:
            OutboundMessageResult 发送结果。

        Raises:
            OutboundDeliveryError: 发送失败。
        """
        ...

    @abstractmethod
    async def send_private_note(
        self,
        platform_conversation_id: str,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> OutboundMessageResult:
        """
        发送内部备注（仅客服可见，终端用户不可见）。

        可选实现，默认返回 NotImplementedError。
        """
        ...


# ── 人工接管信号 ──────────────────────────────────────────────────


class HandoffReason(str, Enum):
    """转人工的触发原因。"""

    CUSTOMER_REQUEST = "customer_request"
    CONFIDENCE_LOW = "confidence_low"
    SENSITIVE_TOPIC = "sensitive_topic"
    MAX_TURNS_EXCEEDED = "max_turns_exceeded"
    ESCALATION = "escalation"
    OTHER = "other"


class HandoffMetadata(BaseModel):
    """转人工的附加信息。"""

    model_config = ConfigDict(extra="allow")

    suggested_team: str | None = None
    suggested_agent: str | None = None
    priority: str | None = None  # "low" / "normal" / "high" / "urgent"
    summary: str | None = None  # AI 为客户坐席生成的对话摘要


class HandoffResult(BaseModel):
    """转人工操作结果。"""

    ok: bool
    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConnectorHandoff(ABC):
    """
    Human handoff 执行器基类。

    agent 在响应中触发转人工信号 → connector 监听 handoff item →
    执行对应平台转人工操作。

    示例：
        Chatwoot: toggle_status → open + assign team/agent
        Intercom: POST /conversations/{id}/parts (note) + assign
        Zendesk: 创建 ticket + 标记当前对话待处理
    """

    @abstractmethod
    async def execute_handoff(
        self,
        platform_conversation_id: str,
        reason: HandoffReason,
        *,
        metadata: HandoffMetadata | None = None,
    ) -> HandoffResult:
        """
        执行平台侧转人工操作。

        Args:
            platform_conversation_id: 平台侧会话 ID。
            reason: 转人工触发原因。
            metadata: 附加信息（建议的团队/坐席、优先级等）。

        Returns:
            HandoffResult 操作结果。
        """
        ...


# ── 平台会话生命周期事件 ──────────────────────────────────────────


class PlatformConversationEventType(str, Enum):
    """平台会话状态变化事件类型。"""

    ASSIGNED_TO_HUMAN = "assigned_to_human"
    ASSIGNED_TO_BOT = "assigned_to_bot"
    RESOLVED = "resolved"
    REOPENED = "reopened"
    CLOSED = "closed"
    SNOOZED = "snoozed"
    USER_MESSAGE = "user_message"
    USER_TYPING = "user_typing"
    CUSTOM = "custom"


class PlatformConversationEvent(BaseModel):
    """
    平台会话生命周期事件。

    connector 把平台的会话状态变化（如人工接管后、客户主动关闭等）
    注入到 anyagent 的 event store，供 agent 在后续轮次感知。
    """

    model_config = ConfigDict(extra="allow")

    session_key: str
    event_type: PlatformConversationEventType
    timestamp_ms: int | None = None
    platform: str | None = None
    platform_conversation_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Agent 层 Handoff 信号 ─────────────────────────────────────────


class HandoffOutputItem(BaseModel):
    """
    Agent 在 /v1/responses 输出中产生的转人工信号（output item）。

    这是 agent loop 中的结构化 output item，不属于 platform connector 层，
    而是 agent 向 Gateway 层声明的"需要人工介入"信号。

    connector 监听到 handoff item → 执行对应平台转人工操作。
    """

    model_config = ConfigDict(extra="allow")

    type: str = Field(default="handoff", frozen=True)
    reason: HandoffReason = Field(default=HandoffReason.OTHER)
    metadata: HandoffMetadata = Field(default_factory=HandoffMetadata)


# ── Connector 注册描述符 ──────────────────────────────────────────


@dataclass(frozen=True)
class ConnectorDescriptor:
    """
    Connector 注册描述符，由插件在 register(api) 中向 Gateway 注册。
    """

    channel: str  # 平台标识：chatwoot / intercom / zendesk / telegram / ...
    display_name: str | None = None
    webhook_auth: ConnectorWebhookAuth | None = None
    outbound_delivery: ConnectorOutboundDelivery | None = None
    handoff: ConnectorHandoff | None = None

    def __post_init__(self) -> None:
        if not self.channel or not self.channel.strip():
            raise ValueError("channel must be non-empty")


# ── 平台专用 session_key 格式 helpers ─────────────────────────────


def chatwoot_session_key(*, account_id: str | int, conversation_id: str | int) -> str:
    """
    Chatwoot 平台 session_key 格式：
        chatwoot:{account_id}:{conversation_id}
    """
    return f"chatwoot:{account_id}:{conversation_id}"


def telegram_session_key(*, chat_id: str | int, topic_id: str | int | None = None) -> str:
    """
    Telegram 平台 session_key 格式：
        telegram:{chat_id}[:{topic_id}]
    """
    base = f"telegram:{chat_id}"
    if topic_id is not None:
        base += f":{topic_id}"
    return base


def intercom_session_key(*, conversation_id: str) -> str:
    """
    Intercom 平台 session_key 格式：
        intercom:{conversation_id}
    """
    return f"intercom:{conversation_id}"
