"""
Chatwoot Connector — 插件入口。

通过 register(api) 注册到 anyagent Gateway：
- Webhook 路由：POST /gateway/chatwoot/webhook
- 渠道注册：channel = "chatwoot"
- 工具注册：
  - app.chatwoot.send_message: agent 发送消息到 Chatwoot 会话
  - app.chatwoot.handoff: agent 触发转人工
- 生命周期 hooks：记录 connector 关键事件
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import httpx
from anyagent.gateway.plugins import WebhookRoute
from anyagent.observability import emit_observability_event
from anyagent.plugins.hooks import HookContext
from anyagent.tool_runtime.models import ToolDefinition

from anyagent.plugins.builtin.chatwoot_connector.chatwoot import (
    ChatwootHandoff,
    ChatwootOutboundDelivery,
    ChatwootWebhookAuth,
    build_platform_event_from_webhook,
    extract_chatwoot_page_context,
)

_LOGGER = logging.getLogger(__name__)


# ── 插件生命周期 hooks ───────────────────────────────────────────


def on_agent_start(context: HookContext) -> None:
    """Agent 启动时记录 connector 上下文。"""
    _LOGGER.info(
        "chatwoot connector: agent_start agent_id=%s session_key=%s response_id=%s",
        context.agent_id,
        context.session_key,
        context.response_id,
    )


def on_agent_end(context: HookContext) -> None:
    """Agent 结束时的清理操作。"""
    _LOGGER.info(
        "chatwoot connector: agent_end agent_id=%s session_key=%s",
        context.agent_id,
        context.session_key,
    )


# ── Webhook 处理器 ────────────────────────────────────────────────


async def _handle_chatwoot_webhook(
    *,
    request: Any,
    headers: dict[str, str],
    raw_body: bytes,
    verified_auth: Any = None,
    state: Any,
    connector: Any,
) -> dict[str, Any]:
    """
    Chatwoot webhook 入口处理器。

    路由规则：
    - POST /gateway/chatwoot/webhook/{agent_id} → 路由到指定 agent
    - POST /gateway/chatwoot/webhook             → fallback 到 catalog 第一个 exposed agent

    处理流程：
    1. 签名验证（已在 _mount_webhook_route 中完成）
    2. 从 URL path 提取目标 agent_id
    3. 解析 webhook body
    4. 构建 platform event 并注入到 event store
    5. 如果是 message_created 事件 → 调用 Agent API 处理
    6. 将 agent 回复写回 Chatwoot 会话
    """
    try:
        body = json.loads(raw_body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {"ok": False, "error": "invalid JSON body"}

    event_name = body.get("event", "")
    page_context = extract_chatwoot_page_context(body)
    _LOGGER.info(
        "chatwoot webhook received: event=%s page_context=%s",
        event_name,
        page_context,
    )

    # 构建 platform event 并写入 event store（供 agent 感知会话状态）
    # message_created: account/conversation 在顶层（message.webhook_data 展开）
    # conversation_*:   account 不出现，conversation 字段直接展开到顶层，id=display_id
    account_id = str(body.get("account", {}).get("id", "")
                      or (verified_auth.account_id if verified_auth else "")
                      or "")
    conversation = body.get("conversation", {})
    conversation_id = str(conversation.get("id", "") or body.get("id", ""))

    platform_event = build_platform_event_from_webhook(
        account_id=account_id,
        webhook_body=body,
    )

    # 注入到 event store
    try:
        await state.events.append(
            response_id=f"platform::{platform_event.session_key}::{event_name}",
            event=f"platform.conversation.{event_name}",
            data=platform_event.model_dump_json(exclude_none=True),
        )
    except Exception as exc:  # noqa: BLE001
        # Don't silently drop: keep the log and emit a warning observability
        # event so operators can see platform events are no longer persisting.
        _LOGGER.warning("failed to persist platform event: %s", exc)
        emit_observability_event(
            "chatwoot.platform_event.persist_failed",
            category="server",
            level="warning",
            payload={
                "session_key": platform_event.session_key,
                "event_name": event_name,
                "reason": str(exc)[:300],
            },
        )

    # 如果是 message_created（用户发送消息），触发 Agent 处理
    if event_name == "message_created":
        # 只处理 incoming 消息（来自客户），跳过 outgoing（bot/agent 发出的）避免无限循环
        message_type = body.get("message_type")
        if message_type != "incoming":
            _LOGGER.debug("skipping non-incoming message: message_type=%s", message_type)
            return {"ok": True, "event": event_name, "skipped": True, "reason": f"message_type={message_type}"}

        if _chatwoot_process_incoming_async():
            _schedule_incoming_message_processing(
                body=body,
                account_id=account_id,
                conversation_id=conversation_id,
                request=request,
                state=state,
                connector=connector,
            )
            return {
                "ok": True,
                "event": event_name,
                "accepted": True,
                "processed": False,
                "reason": "processing_async",
            }

        result = await _process_incoming_message(
            body=body,
            account_id=account_id,
            conversation_id=conversation_id,
            request=request,
            state=state,
            connector=connector,
        )
        return {"ok": True, "event": event_name, **result}

    # 其他事件（status changes, resolved 等）仅记录
    return {
        "ok": True,
        "event": event_name,
        "platform_event": platform_event.model_dump(exclude_none=True),
    }


def _chatwoot_process_incoming_async() -> bool:
    raw = os.getenv("ANYAGENT_CHATWOOT_ASYNC_PROCESSING", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _schedule_incoming_message_processing(
    *,
    body: dict[str, Any],
    account_id: str,
    conversation_id: str,
    request: Any,
    state: Any,
    connector: Any,
) -> None:
    task = asyncio.create_task(
        _process_incoming_message(
            body=body,
            account_id=account_id,
            conversation_id=conversation_id,
            request=request,
            state=state,
            connector=connector,
        )
    )

    def _log_background_result(done: asyncio.Task[dict[str, Any]]) -> None:
        try:
            result = done.result()
        except Exception as exc:  # noqa: BLE001
            # Task-level failure (e.g. crash outside _process_incoming_message's
            # internal guard). The internal failure branches already emitted
            # their own event; only emit here for failures that escaped.
            _LOGGER.exception("failed to process incoming chatwoot message in background: %s", exc)
            from anyagent.gateway.connector_contracts import chatwoot_session_key

            emit_observability_event(
                "chatwoot.background.failed",
                category="server",
                level="error",
                payload={
                    "session_key": chatwoot_session_key(account_id=account_id, conversation_id=conversation_id),
                    "reason": f"background task crashed: {exc}"[:300],
                },
            )
            return
        if not result.get("processed"):
            _LOGGER.warning("chatwoot background processing finished without processing: %s", result)
        else:
            _LOGGER.info("chatwoot background processing completed: %s", result)

    task.add_done_callback(_log_background_result)


async def _process_incoming_message(
    *,
    body: dict[str, Any],
    account_id: str,
    conversation_id: str,
    request: Any,
    state: Any,
    connector: Any,
) -> dict[str, Any]:
    """
    处理入站消息：调用 Agent API 生成回复，通过 Chatwoot API 写回。
    """
    from anyagent.gateway.connector_contracts import HandoffOutputItem, chatwoot_session_key

    message_content = _extract_message_content(body)

    if not message_content:
        return {"processed": False, "reason": "empty message"}

    # 构建 session key
    session_key = chatwoot_session_key(account_id=account_id, conversation_id=conversation_id)

    # 从 URL path param 提取目标 agent_id（/gateway/chatwoot/webhook/{agent_id}）
    target_agent_id = ""
    path_params = getattr(request, "path_params", {})
    if isinstance(path_params, dict):
        target_agent_id = str(path_params.get("agent_id", "")).strip()
    if not target_agent_id:
        if hasattr(state, "catalog") and state.catalog.packs:
            exposed = [aid for aid, pack in state.catalog.packs.items() if pack.spec.exposed]
            if exposed:
                target_agent_id = exposed[0]
        if not target_agent_id:
            target_agent_id = "main"

    request_body: dict[str, Any] = {
        "input": [
            {"role": "user", "content": message_content}
        ],
        "tools": [_gateway_handoff_tool_schema()],
        "metadata": {
            "agent_id": target_agent_id,
            "session_key": session_key,
            "channel": "chatwoot",
            "platform_conversation_id": conversation_id,
            "context": {
                "channel": {
                    "provider": "chatwoot",
                    "account_id": account_id,
                    "thread_id": conversation_id,
                    "ext": {
                        "platform_conversation_id": conversation_id,
                    },
                }
            },
        },
        "stream": False,
    }
    page_context = extract_chatwoot_page_context(body)
    if page_context:
        request_body["metadata"]["context"]["channel"]["ext"]["chatwoot_page_context"] = page_context
        request_body["input"].insert(
            0,
            {
                "role": "developer",
                "content": _render_chatwoot_page_context(page_context),
            },
        )

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=request.app),
            base_url="http://anyagent.local",
        ) as client:
            headers = {}
            if isinstance(state.api_key, str) and state.api_key:
                headers["Authorization"] = f"Bearer {state.api_key}"
            response = await client.post("/v1/responses", headers=headers, json=request_body)

        if response.status_code >= 400:
            emit_observability_event(
                "chatwoot.background.failed",
                category="server",
                level="error",
                payload={
                    "agent_id": target_agent_id,
                    "session_key": session_key,
                    "status_code": response.status_code,
                    "reason": f"agent response failed: {response.status_code}",
                    "response_text": (response.text or "")[:300],
                },
            )
            return {
                "processed": False,
                "reason": f"agent response failed: {response.status_code}",
                "status_code": response.status_code,
                "response_text": response.text,
            }

        payload = response.json()
        reply_text, handoff_item = _extract_reply_and_handoff(payload)

        if reply_text and connector and getattr(connector, "outbound", None) is not None:
            await connector.outbound.send_message(
                platform_conversation_id=conversation_id,
                content=reply_text,
                content_type="text",
            )

        handoff_result = None
        if handoff_item is not None and connector and getattr(connector, "handoff", None) is not None:
            handoff_result = await connector.handoff.execute_handoff(
                platform_conversation_id=conversation_id,
                reason=handoff_item.reason,
                metadata=handoff_item.metadata,
            )
        tool_handoff_executed = await _response_used_gateway_handoff(
            state=state,
            response_id=str(payload.get("id") or ""),
        )

        return {
            "processed": True,
            "reply_sent": bool(reply_text and connector and getattr(connector, "outbound", None)),
            "handoff_triggered": handoff_item is not None or tool_handoff_executed,
            "handoff_executed": bool((handoff_result and handoff_result.ok) or tool_handoff_executed),
            "status_code": response.status_code,
        }

    except Exception as exc:  # noqa: BLE001
        _LOGGER.exception("failed to process incoming chatwoot message: %s", exc)
        emit_observability_event(
            "chatwoot.background.failed",
            category="server",
            level="error",
            payload={
                "agent_id": target_agent_id,
                "session_key": session_key,
                "reason": str(exc)[:300],
            },
        )
        return {"processed": False, "reason": str(exc)}


def _extract_message_content(body: dict[str, Any]) -> str | None:
    """从 Chatwoot webhook body 中提取消息文本。

    Chatwoot message_created 事件：content 位于顶层（message.webhook_data 展开）。
    结构参考: app/models/message.rb #webhook_data
    """
    # message_created/updated: content 在顶层（webhook_data 展开）
    content = body.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()

    # 部分 webhook 配置下 content 嵌套在 message 内
    message = body.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()

    # conversation_created: 回退到 conversation.messages 中第一条
    conversation = body.get("conversation", {})
    messages = conversation.get("messages", [])
    if isinstance(messages, list) and messages:
        first_msg = messages[0]
        if isinstance(first_msg, dict):
            msg_content = first_msg.get("content")
            if isinstance(msg_content, str) and msg_content.strip():
                return msg_content.strip()

    return None


def _render_chatwoot_page_context(page_context: dict[str, str]) -> str:
    lines = ["Chatwoot page context for this visitor:"]
    labels = {
        "referer": "Referer",
        "entry_url": "Entry URL",
        "entry_path": "Entry path",
        "entry_title": "Entry title",
        "entry_locale": "Entry locale",
        "widget_language": "Widget language",
        "browser_language": "Browser language",
    }
    for key, label in labels.items():
        value = page_context.get(key)
        if isinstance(value, str) and value.strip():
            lines.append(f"- {label}: {value.strip()}")
    return "\n".join(lines)


def _extract_reply_and_handoff(payload: dict[str, Any]) -> tuple[str, Any | None]:
    """从 Agent API 响应 payload 中提取回复文本与 handoff item。"""
    output = payload.get("output", [])
    if not isinstance(output, list):
        return "", None

    texts: list[str] = []
    handoff_item = None
    for item in output:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type", "")
        if item_type == "message":
            content_list = item.get("content", [])
            if isinstance(content_list, list):
                for part in content_list:
                    if isinstance(part, dict) and part.get("type") == "output_text":
                        text = part.get("text", "")
                        if isinstance(text, str) and text.strip():
                            texts.append(text.strip())
        elif item_type == "handoff":
            from anyagent.gateway.connector_contracts import HandoffOutputItem

            handoff_item = HandoffOutputItem.model_validate(item)

    return "\n\n".join(texts), handoff_item


async def _response_used_gateway_handoff(*, state: Any, response_id: str) -> bool:
    if not isinstance(response_id, str) or not response_id.strip():
        return False
    events = await state.events.list_events(response_id=response_id.strip(), last_seq=0, limit=200)
    for event in events.events:
        if event.event not in {"anyagent.tool.planned", "anyagent.tool.result"}:
            continue
        try:
            payload = json.loads(event.data)
        except Exception:  # noqa: BLE001
            continue
        tool_name = payload.get("tool_name")
        if tool_name in {"gateway.handoff", "app.chatwoot.handoff"}:
            return True
    return False


def _gateway_handoff_tool_schema() -> dict[str, Any]:
    return {
        "type": "function",
        "name": "gateway.handoff",
        "description": "Escalate the current platform conversation to a human operator through the active gateway connector.",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["reason"],
            "properties": {
                "reason": {
                    "type": "string",
                    "enum": [
                        "customer_request",
                        "confidence_low",
                        "sensitive_topic",
                        "max_turns_exceeded",
                        "escalation",
                        "other",
                    ],
                },
                "suggested_team": {"type": "string"},
                "suggested_agent": {"type": "string"},
                "priority": {"type": "string"},
                "summary": {"type": "string"},
            },
        },
        "strict": True,
    }


# ── 插件注册入口 ──────────────────────────────────────────────────


def register(api: Any) -> None:
    """
    Chatwoot Connector 插件注册入口。

    在 Gateway + Tool Runtime 双宿主下注册：
    - 渠道 connector（chatwoot）
    - Webhook 路由（POST /gateway/chatwoot/webhook）
    - 工具（app.chatwoot.send_message / app.chatwoot.handoff）

    环境变量配置（推荐走 Credential Vault，以下为开发环境 fallback）：
    - ANYAGENT_CHATWOOT_URL: Chatwoot 实例 URL
    - ANYAGENT_CHATWOOT_ACCOUNT_ID: Chatwoot account ID
    - ANYAGENT_CHATWOOT_ACCESS_TOKEN: Agent Bot access_token
    - ANYAGENT_CHATWOOT_WEBHOOK_SECRET: webhook HMAC secret（或 credential_id 引用）
    """

    chatwoot_url = os.getenv("ANYAGENT_CHATWOOT_URL", "https://app.chatwoot.com")
    account_id = os.getenv("ANYAGENT_CHATWOOT_ACCOUNT_ID", "1")
    access_token = os.getenv("ANYAGENT_CHATWOOT_ACCESS_TOKEN", "")
    webhook_secret = os.getenv("ANYAGENT_CHATWOOT_WEBHOOK_SECRET", "")
    webhook_secret_kind_value = os.getenv("ANYAGENT_CHATWOOT_CREDENTIAL_KIND", "secret")

    # 构建 connector 实例
    _auth = ChatwootWebhookAuth()
    _outbound = ChatwootOutboundDelivery(
        chatwoot_url=chatwoot_url,
        account_id=account_id,
        access_token=access_token,
    )
    _handoff = ChatwootHandoff(
        chatwoot_url=chatwoot_url,
        account_id=account_id,
        access_token=access_token,
    )

    _chatwoot_webhook_secret = webhook_secret
    class _ChatwootConnector:
        """Chatwoot Connector 运行时实例。"""
        channel = "chatwoot"
        display_name = "Chatwoot"
        webhook_auth = _auth
        outbound = _outbound
        handoff = _handoff
        webhook_secret_credential_id = os.getenv("ANYAGENT_CHATWOOT_CREDENTIAL_ID", "")
        webhook_secret = _chatwoot_webhook_secret

    connector_instance = _ChatwootConnector()
    connector_instance.webhook_secret_kind = webhook_secret_kind_value

    # 注册渠道 connector
    if hasattr(api, "registerChannel"):
        api.registerChannel(connector_instance)

    # 注册 webhook 路由
    # 两条路由共享同一个 handler：
    #   /chatwoot/webhook/{agent_id} — 路径绑定目标 agent（推荐）
    #   /chatwoot/webhook            — fallback 到 catalog 第一个 exposed agent
    if hasattr(api, "registerWebhookRoute"):
        api.registerWebhookRoute(WebhookRoute(
            path="/chatwoot/webhook/{agent_id}",
            channel="chatwoot",
            methods=("POST",),
            handler=_handle_chatwoot_webhook,
        ))
        api.registerWebhookRoute(WebhookRoute(
            path="/chatwoot/webhook",
            channel="chatwoot",
            methods=("POST",),
            handler=_handle_chatwoot_webhook,
        ))

    # 注册工具
    if hasattr(api, "registerTool"):

        async def _tool_send_message(args: dict[str, Any], context: dict[str, Any]) -> str:
            """工具：agent 发送消息到 Chatwoot 会话。"""
            conversation_id = str(args.get("conversation_id", ""))
            content = str(args.get("content", ""))
            result = await _outbound.send_message(
                platform_conversation_id=conversation_id,
                content=content,
            )
            return json.dumps({"ok": result.ok, "message_id": result.platform_message_id})

        api.registerTool(
            ToolDefinition(
                name="app.chatwoot.send_message",
                description="发送消息到 Chatwoot 会话。",
                category="app",
                kind="command",
                parameters={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["conversation_id", "content"],
                    "properties": {
                        "conversation_id": {
                            "type": "string",
                            "description": "Chatwoot conversation ID。",
                        },
                        "content": {
                            "type": "string",
                            "description": "要发送的消息内容（支持 markdown）。",
                        },
                    },
                },
            ),
            _tool_send_message,
        )

        async def _tool_handoff(args: dict[str, Any], context: dict[str, Any]) -> str:
            """工具：触发 Chatwoot 转人工。"""
            from anyagent.gateway.connector_contracts import HandoffReason, HandoffMetadata

            conversation_id = str(args.get("conversation_id", ""))
            reason_str = str(args.get("reason", "customer_request"))
            suggested_team = args.get("suggested_team")
            summary = args.get("summary")

            try:
                reason = HandoffReason(reason_str)
            except ValueError:
                reason = HandoffReason.CUSTOMER_REQUEST

            metadata = HandoffMetadata(
                suggested_team=str(suggested_team) if suggested_team else None,
                summary=str(summary) if summary else None,
            )

            result = await _handoff.execute_handoff(
                platform_conversation_id=conversation_id,
                reason=reason,
                metadata=metadata,
            )
            return json.dumps({"ok": result.ok, "reason": result.reason})

        api.registerTool(
            ToolDefinition(
                name="app.chatwoot.handoff",
                description="将 Chatwoot 会话转接给人工坐席。触发后会话状态变为 open，可选指派到特定团队/坐席。",
                category="app",
                kind="command",
                parameters={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["conversation_id"],
                    "properties": {
                        "conversation_id": {
                            "type": "string",
                            "description": "Chatwoot conversation ID。",
                        },
                        "reason": {
                            "type": "string",
                            "enum": ["customer_request", "confidence_low", "sensitive_topic", "max_turns_exceeded", "escalation"],
                            "description": "转人工原因。",
                        },
                        "suggested_team": {
                            "type": "string",
                            "description": "建议指派的团队 ID。",
                        },
                        "summary": {
                            "type": "string",
                            "description": "AI 为客户坐席生成的对话摘要。",
                        },
                    },
                },
            ),
            _tool_handoff,
        )

    _LOGGER.info(
        "chatwoot connector registered (url=%s, account_id=%s)",
        chatwoot_url,
        account_id,
    )
