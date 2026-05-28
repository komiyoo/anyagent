<!--
---
doc_kind: architecture
status: stable
tags: ["gateway", "platform", "connector", "routing", "session"]
summary: Gateway 与平台 connector 的职责边界、平台能力注入、session/thread 绑定和多 agent 路由。
req: ["requirements.md#req-6", "requirements.md#req-6-1", "requirements.md#req-6-3", "requirements.md#req-6-4"]
---
-->

# Gateway Platform Routing

Gateway 负责连接外部平台、线程映射、消息回传与平台交互渲染。工具执行、权限、幂等与审计属于 Tool Runtime。

## 职责边界

- Gateway：channel connector、webhook 路由、消息回传渲染、平台线程到 `session_key` 的映射。
- Tool Runtime：`feishu.*` / `discord.*` / `telegram.*` 等 channel tools 的注册、执行、权限、幂等与审计。
- Agent API：`POST /v1/responses`、agent loop、SSE、Session/Run/Event、manifest 合并。

平台插件可以同一份代码在不同宿主注册不同能力：

- Gateway 侧：`registerChannel(connector)`、`registerWebhookRoute(...)`。
- Tool Runtime 侧：`registerTool(...)` 注册 `<channel>.*` tools。

业务项目只需要自定义 `app.*` 工具时，不必实现完整平台插件。

## 平台能力注入

飞书能力示例：

- `feishu.directory.get_chat_members(chat_id)`
- `feishu.doc.create(title, folder_id, content...)`
- `feishu.doc.patch(doc_id, ops...)`
- `feishu.drive.upload(file)`
- `feishu.perm.grant(doc_id, user_id, role)`

执行形态：

- tools 注册到 Tool Runtime。
- Tool Runtime 执行时使用 credential/auth_ref 与标准化 channel context。
- Gateway 负责把 agent streaming delta 映射成平台消息编辑、卡片更新或聚合回复。

## 会话线程绑定策略

Gateway 必须保证：

- 同一个平台 thread 映射到稳定 `session_key`。
- 会话内串行，避免同一 thread 并发写上下文导致乱序。
- 多 agent 场景下，同一个平台 thread + 同一个 `agent_id` 映射到同一个 `session_partition_key`。

推荐格式：

```text
session_partition_key = "{agent_id}::{session_key}"
```

示例 `session_key`：

- `feishu:{chat_id}:{thread_id_or_root_msg_id}`
- `discord:{guild_id}:{channel_id}:{thread_id_or_msg_id}`
- `telegram:{chat_id}:{topic_id_or_msg_id}`

## 多 Agent 路由

Gateway 调用 Agent API 时必须在 `metadata.agent_id` 里显式带上最终 `agent_id`。

允许并存的策略：

- Static Bot Mapping：按 bot 实例或应用配置固定 `agent_id`。
- Channel Mapping：按群/频道配置 `agent_id`。
- Message Hint：从显式 hint 解析，例如 `@legal`、`/agent legal`、`$agent:legal`。
- Thread Binding：对某个 thread 一次性绑定，后续自动复用。

无论采用哪种策略，结果都必须可解释、可审计。
