# Chatwoot Inbound Channel Connector

Chatwoot 入站渠道 connector 参考实现，属于 anyagent Gateway 层 plugin。

## 功能概览

| 能力 | 状态 | 说明 |
|------|------|------|
| Inbound webhook 接收 | ✅ | `POST /gateway/chatwoot/webhook` — 接收 Chatwoot Agent Bot webhook 事件 |
| Webhook 签名验证 | ✅ | HMAC-SHA256 验签（`X-Chatwoot-Signature` header） |
| Platform session binding | ✅ | `session_key = "chatwoot:{account_id}:{conversation_id}"` |
| Outbound message delivery | ✅ | 通过 Chatwoot Agent Bot API 回写消息到会话 |
| Human handoff | ✅ | handoff 切换会话状态 → open，并 assign team/agent + AI 摘要 note；`CHATWOOT_STATUS_CHANGES=false` 时不修改会话状态 |
| Skip when assigned | ✅ | 会话已分配给真人坐席（`meta.assignee_type=User`）时不调用 agent、不写回客户消息；`CHATWOOT_SKIP_WHEN_ASSIGNED_TO_HUMAN=false` 时关闭 |
| Open on reply | ✅ | bot 回复成功后将会话保持为 open（pending / resolved / snoozed / 缺 status 都会打开；已是 open 则不动）。从不 resolve / snooze。`CHATWOOT_STATUS_CHANGES=false` 时关闭 |
| Conversation lifecycle events | ✅ | 监听 `message_created` / `conversation_resolved` 等事件并注入 event store |
| Agent 主动调用工具 | ✅ | `app.chatwoot.send_message` / `app.chatwoot.handoff` 两个系统工具 |
| Tool-based handoff bridge | ✅ | webhook 请求会自动向 `/v1/responses` 注入 `gateway.handoff`，走通用 Tool Runtime 主路径 |
| Typing indicator | ✅ | `CHATWOOT_TYPING_INDICATOR=true` 时调用 Agent API 前打开、发送前关闭（`toggle_typing_status`，同一 bot token）；默认关闭 |
| Reply pacing floor | ✅ | `CHATWOOT_REPLY_PACING_MIN_S` / `_MAX_S` 设定回复节奏下限：本轮耗时不足区间内随机值时补足再发，已超过则立即发。用于 scripted reply 等瞬时回复；默认关闭 |

Scripted reply 可在 Response 消息项附可选的 `content_type` / `content_attributes`。connector 将其传到 Chatwoot outgoing API；普通模型回复和未带属性的 scripted reply 仍是纯文本。可信 workspace 插件可调用 `_process_incoming_message(..., input_source="...")`，复用响应生成、人工接管检查与出站路径；来源写入 Responses 请求 metadata。

## 架构

```
Chatwoot webhook 事件
  ↕
POST /gateway/chatwoot/webhook
  ↕
ChatwootWebhookAuth (验签)
  ↕
Webhook handler (解析事件)
  ↕
Agent API (/v1/responses)  →  agent loop  →  SSE 回复
  ↕
ChatwootOutboundDelivery (回写 Chatwoot API)
```

## 配置

通过环境变量配置（推荐生产环境使用 Credential Vault 管理密钥）。
如果你使用 Chatwoot 官方云，`CHATWOOT_URL` 可直接使用默认值 `https://app.chatwoot.com`：

```bash
export CHATWOOT_URL="https://app.chatwoot.com"
export CHATWOOT_ACCOUNT_ID="1"
export CHATWOOT_ACCESS_TOKEN="your_agent_bot_access_token"
export CHATWOOT_WEBHOOK_SECRET="your_webhook_hmac_secret"
# 可选：默认 true——handoff → open，且 bot 回复后将 pending 会话置为 open。
# 设为 false 时 connector 不修改 Chatwoot 会话状态（handoff 不调用
# toggle_status，仅保留 assignment 与 AI 摘要 private note；消息收发不受影响）。
# export CHATWOOT_STATUS_CHANGES="false"
# 可选：默认 true——会话已分配给真人坐席时跳过 bot 回复。不能用 status=open
# 判断（bot 回复后也会把 pending 置为 open）；依据是 assignee_type=User。
# export CHATWOOT_SKIP_WHEN_ASSIGNED_TO_HUMAN="false"
# 可选：默认关闭——调用 Agent API 期间挂起 typing 指示（需要 bot token 有
# toggle_typing_status 权限；无权限时只 warning，不影响回复）。
# export CHATWOOT_TYPING_INDICATOR="true"
# 可选：默认关闭——回复节奏下限（秒）。本轮从收到 webhook 到准备发送若不足
# [MIN, MAX] 内的随机值则补足；已超过则立即发（floor，不叠加）。等待放在
# 二次人工接管检查之前，等待期间被接管的会话不会被 bot 插话。
# export CHATWOOT_REPLY_PACING_MIN_S="2"
# export CHATWOOT_REPLY_PACING_MAX_S="4"
```

### Credential Vault（生产环境推荐）

```bash
# 设置 webhook 签名密钥到 Credential Vault
curl -X POST http://localhost:8000/admin/credentials \
  -H "Authorization: Bearer <ADMIN_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "credential_id": "chatwoot_webhook_secret",
    "kind": "secret",
    "value": "your_hmac_secret",
    "scope": {"level": "global"}
  }'

export CHATWOOT_CREDENTIAL_ID="chatwoot_webhook_secret"
# 如需沿用历史 kind，可显式声明：
export CHATWOOT_CREDENTIAL_KIND="webhook_secret"
```

## 启动

```bash
anyagent serve \
  --workspace-dir ./workspace \
  --plugin-root packages/anyagent/src/anyagent/plugins/builtin
```

## 注册的工具

### `app.chatwoot.send_message`

Agent 发送消息到 Chatwoot 会话。

```json
{
  "conversation_id": "42",
  "content": "你好！有什么可以帮助你的？"
}
```

### `app.chatwoot.handoff`

将 Chatwoot 会话转接给人工坐席。

```json
{
  "conversation_id": "42",
  "reason": "customer_request",
  "suggested_team": "1",
  "summary": "客户咨询了退款政策，需要人工协助处理"
}
```

### `gateway.handoff`

在 Chatwoot webhook 主链路里，connector 会自动把 `gateway.handoff` 暴露给
`/v1/responses`，并通过 `ToolContext.channel` 绑定当前 `conversation_id`。
这允许 agent 用标准 function-call 路径触发转人工，而不需要上游 provider
原生支持自定义 `handoff` output item。

## 页面上下文

Connector 将入口页面信息写入请求的
`metadata.context.channel.ext.chatwoot_page_context`，并以同一内容记录
`PlatformConversationEvent.metadata.chatwoot_page_context`。

自 0.4.28 起，页面上下文保留 `lt_quick_prompt_id` 和 `quick_prompt_id`，供业务侧识别访客点击的快捷问题。字段来自 conversation、contact、sender、meta.sender 的 `custom_attributes`，按此顺序合并，后者覆盖前者；只接收非空字符串并去除两端空白。字段不会触发 SDK 内的业务路由。

自 0.4.29 起，`message_created` / `message_updated` 平台事件的 metadata 还保留消息本身的 `message_id`（正整数，归一化为字符串）与 `message_type`（`incoming` / `outgoing` / `template` / `activity`）。非法 ID 或未知类型省略。处理入站消息时，同一 ID 写入 `metadata.context.channel.message_id`；`anyagent.response.request` 事件记录可选的 `channel_context: {provider, message_id}`，不复制 channel 的扩展数据。日志消费者可按 session + message ID 关联 `webhook_timestamp`，避免问候语、Bot 回复或重叠轮次造成时间错配。缺少 ID 的旧日志只能估算，不能回填成精确消息时间。

## Session Key 格式

```
chatwoot:{account_id}:{conversation_id}
```

示例：`chatwoot:1:42` → account 1, conversation 42

## 支持的 Webhook 事件

| 事件 | 处理方式 |
|------|---------|
| `message_created` | incoming 且未分配真人坐席：提取消息文本 → 调用 Agent API → 回写回复；已分配 `User`：ack 后跳过 |
| `conversation_resolved` | 记录 event store |
| `conversation_reopened` | 记录 event store |
| `conversation_closed` | 记录 event store |
| `conversation_snoozed` | 记录 event store |
| 其他事件 | 记录为 `PlatformConversationEvent` 到 event store |

## Chatwoot 配置要求

1. 在 Chatwoot 中创建 Agent Bot
2. 配置 webhook URL 指向 `https://your-anyagent/gateway/chatwoot/webhook`
3. 记录 Agent Bot 的 access_token 和 webhook secret
4. 将 Agent Bot 分配到你想要自动化的 Inbox
