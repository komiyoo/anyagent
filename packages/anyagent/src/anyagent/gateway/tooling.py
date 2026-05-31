from __future__ import annotations

import json
from typing import Any

from anyagent.gateway.connector_contracts import HandoffMetadata, HandoffReason
from anyagent.gateway.plugins import GatewayRegistry
from anyagent.tool_runtime.models import ToolDefinition
from anyagent.tool_runtime.registry import ToolRegistry


def register_gateway_tools(*, registry: ToolRegistry, gateway_registry: GatewayRegistry) -> None:
    async def gateway_handoff(args: dict[str, Any], context: dict[str, Any]) -> str:
        tool_context = context.get("context")
        channel = tool_context.get("channel") if isinstance(tool_context, dict) else None
        if not isinstance(channel, dict):
            raise ValueError("gateway.handoff requires tool context.channel")

        provider = str(channel.get("provider") or "").strip()
        if not provider:
            raise ValueError("gateway.handoff requires channel.provider")

        connector = gateway_registry.channel_connectors.get(provider)
        if connector is None:
            raise ValueError(f"unknown gateway connector: {provider}")

        handoff = getattr(connector, "handoff", None)
        if handoff is None:
            raise ValueError(f"connector does not support handoff: {provider}")

        ext = channel.get("ext") if isinstance(channel.get("ext"), dict) else {}
        platform_conversation_id = str(
            args.get("platform_conversation_id")
            or ext.get("platform_conversation_id")
            or channel.get("thread_id")
            or channel.get("chat_id")
            or ""
        ).strip()
        if not platform_conversation_id:
            raise ValueError("gateway.handoff requires platform conversation id in args or channel context")

        reason_raw = str(args.get("reason") or HandoffReason.OTHER.value).strip()
        try:
            reason = HandoffReason(reason_raw)
        except ValueError:
            reason = HandoffReason.OTHER

        metadata = HandoffMetadata(
            suggested_team=_optional_str(args.get("suggested_team")),
            suggested_agent=_optional_str(args.get("suggested_agent")),
            priority=_optional_str(args.get("priority")),
            summary=_optional_str(args.get("summary")),
        )
        result = await handoff.execute_handoff(
            platform_conversation_id=platform_conversation_id,
            reason=reason,
            metadata=metadata,
        )
        return json.dumps(result.model_dump(exclude_none=True), ensure_ascii=False)

    registry.register_tool(
        ToolDefinition(
            name="gateway.handoff",
            description="Escalate the active platform conversation to a human operator through the current gateway connector.",
            category="channel",
            parameters={
                "type": "object",
                "additionalProperties": False,
                "required": ["reason"],
                "properties": {
                    "reason": {
                        "type": "string",
                        "enum": [reason.value for reason in HandoffReason],
                        "description": "Why the conversation should be escalated to a human.",
                    },
                    "platform_conversation_id": {
                        "type": "string",
                        "description": "Optional explicit platform conversation id override.",
                    },
                    "suggested_team": {"type": "string"},
                    "suggested_agent": {"type": "string"},
                    "priority": {"type": "string"},
                    "summary": {"type": "string"},
                },
            },
        ),
        gateway_handoff,
    )


def _optional_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None
