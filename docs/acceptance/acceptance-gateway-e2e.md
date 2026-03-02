# Gateway 端到端验收清单（v0）

对应需求：`requirements.md#req-9-2`

本清单用于验收“平台消息 → Gateway → Agent API → Tool Runtime → 平台回消息”的最小闭环。v0 阶段建议先打通一个平台（推荐飞书）。

## 0. 前置条件

- Agent API 已可用：`POST /v1/responses`（支持 `stream=true` SSE）
- Tool Runtime 已可用：`/internal/tools/manifest` + `/internal/tools/execute`
- Gateway 具备：
  - webhook 入口（接收平台消息事件）
  - session/thread 绑定（生成稳定 `session_key`）
  - 调用 Agent API 并消费 SSE
  - 调用平台发消息/编辑消息 API

## 1. 会话映射（必测）

验收点：
- 同一平台 thread 映射到同一个 `session_key`
- `session_partition_key = "{agent_id}::{session_key}"` 用于 keyed serialization 与日志关联

建议：
- 飞书：`session_key = "feishu:{chat_id}:{thread_id_or_root_msg_id}"`

## 2. 入站 → Agent API（必测）

验收点：
- Gateway 调用 Agent API 时，必须携带：
  - `Authorization: Bearer <AGENT_API_KEY>`
  - `metadata.session_key`（稳定、跨请求一致）
  - `metadata.agent_id`（默认 `main` 或业务指定）
  - `metadata.context.channel`（至少包含 provider/chat/thread 等，用于策略与审计）

## 3. SSE 消费与回消息（必测）

验收点：
- Gateway 能消费 `stream=true` 的 SSE
- 能将增量输出映射为“打字/编辑消息/卡片更新”等平台能力
- SSE 结束条件正确（`[DONE]`）

降级策略（允许）：
- 平台不支持增量编辑时，可聚合到最终 `response.completed` 后一次性发送

## 4. 平台工具调用（至少 1 个，必测）

目的：验证 channel tools 的注册、披露（manifest）、执行（execute）与权限边界可用。

以飞书为例（Tool Runtime plugin 提供的工具）：
- `feishu.directory.get_chat_members`
- `feishu.doc.create`

验收点：
- Tool Runtime policy 默认拒绝 channel tools；当且仅当 allowlist 明确允许（例如 `allow_tools=["feishu.*"]`）时才可见/可执行
- 工具执行产生结构化日志（含 `audit_ref`），且不泄漏 token/敏感参数

## 5. 会话内串行（必测）

验收点：
- 同一 `session_partition_key` 的两条平台消息“快速连续到达”时，Gateway/Agent API 不应并发跑两个 agent loop
- 用户看到的回复顺序与平台消息顺序一致（至少不会交错覆盖）

## 6. 失败场景（建议测）

- 平台 webhook 重试（同一 message id 多次到达）不应触发重复回复（需结合 Idempotency-Key / 去重策略）
- Tool Runtime 409 `toolset_version_mismatch` 能自动恢复（刷新 manifest + 单次重试）
- 平台 token 失效时，错误应可定位（不泄漏 token，记录 `audit_ref` / `auth_ref`）

