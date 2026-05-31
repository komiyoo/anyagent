"""
Gateway（SDK 子模块，占位）：

后续用于承载：
- connector 插件契约
- channel context / message rendering helpers
"""

__all__ = [
    "AgentRouter",
    "AgentRouterConfig",
    "AgentRoutingDecision",
    "AgentRoutingError",
    "ConnectorDescriptor",
    "ConnectorHandoff",
    "ConnectorOutboundDelivery",
    "ConnectorWebhookAuth",
    "GatewayPluginAPI",
    "GatewayRegistry",
    "HandoffMetadata",
    "HandoffOutputItem",
    "HandoffReason",
    "HandoffResult",
    "InMemoryThreadBindingStore",
    "KeyedSequencer",
    "OutboundDeliveryError",
    "OutboundMessageResult",
    "PlatformConversationEvent",
    "PlatformConversationEventType",
    "RoutingStrategy",
    "SessionBinding",
    "SessionBindingError",
    "WebhookAuthError",
    "WebhookAuthSuccess",
    "WebhookRoute",
    "bind_session",
    "bind_session_from_tool_context",
    "channel_mapping_key",
    "chatwoot_session_key",
    "intercom_session_key",
    "run_in_session",
    "session_key_for_thread",
    "session_key_from_channel_context",
    "session_partition_key",
    "telegram_session_key",
    "thread_binding_key",
    "validate_agent_id",
]

from .agent_routing import (
    AgentRouter,
    AgentRouterConfig,
    AgentRoutingDecision,
    AgentRoutingError,
    InMemoryThreadBindingStore,
    RoutingStrategy,
    channel_mapping_key,
    thread_binding_key,
    validate_agent_id,
)
from .connector_contracts import (
    ConnectorDescriptor,
    ConnectorHandoff,
    ConnectorOutboundDelivery,
    ConnectorWebhookAuth,
    HandoffMetadata,
    HandoffOutputItem,
    HandoffReason,
    HandoffResult,
    OutboundDeliveryError,
    OutboundMessageResult,
    PlatformConversationEvent,
    PlatformConversationEventType,
    WebhookAuthError,
    WebhookAuthSuccess,
    chatwoot_session_key,
    intercom_session_key,
    telegram_session_key,
)
from .plugins import GatewayPluginAPI, GatewayRegistry, WebhookRoute
from .sequencer import KeyedSequencer
from .session import (
    SessionBinding,
    SessionBindingError,
    bind_session,
    bind_session_from_tool_context,
    run_in_session,
    session_key_for_thread,
    session_key_from_channel_context,
    session_partition_key,
)
