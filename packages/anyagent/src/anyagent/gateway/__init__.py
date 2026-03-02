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
    "GatewayPluginAPI",
    "GatewayRegistry",
    "InMemoryThreadBindingStore",
    "KeyedSequencer",
    "RoutingStrategy",
    "SessionBinding",
    "SessionBindingError",
    "WebhookRoute",
    "bind_session",
    "bind_session_from_tool_context",
    "channel_mapping_key",
    "run_in_session",
    "session_key_for_thread",
    "session_key_from_channel_context",
    "session_partition_key",
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
