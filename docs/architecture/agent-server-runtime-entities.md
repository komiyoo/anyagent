# Agent Server 运行时概念实体（含 Codex 对照）

本文梳理 anyagent `agent-api + tool-runtime` 在 2026-03-04 当前代码中的运行时实体定义与层级关系，并对照 Codex 的 `Connection -> Thread -> Turn -> Item -> ToolCall` 体系，统一术语语义。

说明：

- 本文优先描述“代码真实行为”（as-is），并引用需求锚点说明“规范期望”（to-be）。
- 需求定义基线：`requirements.md#req-2`、`requirements.md#req-4-3`、`requirements.md#req-4-4`、`requirements.md#req-4-5`、`requirements.md#req-5-8`、`requirements.md#req-5-13`。

## 1. 总览：anyagent 与 Codex 的层级映射

| 语义层 | Codex 概念             | anyagent 当前概念                         | 当前是否一等持久化 | 主要标识                                   |
| ------ | ---------------------- | ----------------------------------------- | ------------------ | ------------------------------------------ |
| 传输层 | Connection             | HTTP Request / SSE Stream 连接            | 否                 | 请求上下文（无稳定 connection_id）         |
| 会话层 | Thread / Conversation  | Session（外部会话）                       | 部分               | `session_key`、`session_partition_key`     |
| 协作层 | Thread（child thread） | Multi-Agent Thread                        | 是（内存态）       | `thread_id`、`root_thread_id`              |
| 执行层 | Turn                   | Run 内一次迭代                            | 否（逻辑单元）     | `previous_response_id` 串联                |
| 内容层 | Item                   | OpenAI output item / function_call_output | 否（不独立落库）   | `response.output[*]`、`type`               |
| 工具层 | Tool Call              | Tool / Tool Call                          | 是（调用幂等缓存） | `tool_name`、`tool_call_id`、`response_id` |
| 事件层 | Event Stream           | Event                                     | 是                 | `response_id + seq`                        |

## 2. 实体定义与代码落点

## 2.1 Connection（传输连接）

定义：

- 传输级连接，负责请求接入与流式回传，不承载长期业务状态。
- 对应 Codex 的 JSON-RPC connection 维度，anyagent 当前是 HTTP/SSE 维度。

当前实现：

- `POST /v1/responses` 接入，`stream=true` 走同连接 SSE 推送。
- 连接断开后，恢复依赖 Event Store 补发而非连接本身状态。

证据：

- 同连接 SSE 语义：`requirements.md:272`。
- 实际 SSE 返回：`apps/agent-api/src/anyagent_agent_api/app.py:1174`。
- 断线补发接口：`apps/agent-api/src/anyagent_agent_api/internal/events.py:99`。

## 2.2 Session（Conversation 主边界）

定义：

- Session 是“跨请求 conversation 边界 + 并发串行化边界”。
- 分片键固定为 `session_partition_key = "{agent_id}::{session_key}"`。

当前实现：

- Agent API 从 `metadata.session_key` 读取会话键，不存在则生成临时会话。
- 通过 `session_partition_key` 做 keyed serialization 与 lease lock。
- Session Store 已作为一等运行时实体接入（`none/external` 双模式），快照字段至少包含 `runtime_config + resume_cursor + snapshot_version`。
- 首轮请求会基于 Session 快照自动组装 `previous_response_id`（或 transcript fallback），并在 run 终态回写新游标。

证据：

- 会话键约定：`requirements.md:301`。
- 分片键实现：`packages/anyagent/src/anyagent/gateway/session.py:70`。
- 入口解析：`apps/agent-api/src/anyagent_agent_api/app.py:279`、`apps/agent-api/src/anyagent_agent_api/app.py:284`。
- 会话内串行：`apps/agent-api/src/anyagent_agent_api/app.py:1319`、`apps/agent-api/src/anyagent_agent_api/app.py:1324`。
- Session Store 协议与实现：`apps/agent-api/src/anyagent_agent_api/storage/runtime.py:99`、`apps/agent-api/src/anyagent_agent_api/storage/postgres.py:251`、`apps/agent-api/src/anyagent_agent_api/storage/inmemory.py:168`。
- Session Resume + Runtime Config 组装：`apps/agent-api/src/anyagent_agent_api/app.py:239`、`apps/agent-api/src/anyagent_agent_api/app.py:452`。

## 2.3 Multi-Agent Thread（协作线程）

定义：

- 这是协作编排层 thread，不等于 Session。
- 用于 `spawn_agent/send_input/wait/close/resume` 生命周期管理。

当前实现：

- 主请求会生成稳定 `root_thread_id`，可由 metadata 覆盖当前 `thread_id`。
- 子线程以 `ThreadRecord` 维护 parent/root/depth/status。
- 当前为单实例 in-memory 管理，不是跨实例持久化实体。

证据：

- 根线程生成：`apps/agent-api/src/anyagent_agent_api/app.py:289`。
- thread 元数据读取：`apps/agent-api/src/anyagent_agent_api/app.py:293`。
- 线程模型：`apps/agent-api/src/anyagent_agent_api/multiagent/manager.py:33`。
- in-memory store：`apps/agent-api/src/anyagent_agent_api/multiagent/manager.py:157`。

## 2.4 Run / Response（一次执行实例）

定义：

- 一次 `POST /v1/responses` 对应一次 Run/Response。
- `response_id` 在 anyagent 中即 run 主键。

当前实现：

- `RunRecord` 持久化 `response_id/session_partition_key/idempotency_key/status/final_response_json` 等字段。
- 状态机当前实现值：`started/completed/errored`。
- Idempotency-Key 命中时复用既有 run。

证据：

- run 模型：`apps/agent-api/src/anyagent_agent_api/storage/models.py:10`。
- run 持久化：`apps/agent-api/src/anyagent_agent_api/storage/postgres.py:12`。
- 幂等入口：`apps/agent-api/src/anyagent_agent_api/app.py:357`。

## 2.5 Turn（run 内推理迭代单元）

定义：

- Turn 是 run 内一次“模型完成 -> (可选) 工具调用 -> 回灌继续推理”的逻辑单元。
- 当前没有独立 `turn_id` 表；Turn 在运行时以内存语义驱动，但在 `STORAGE_MODE=none` 下会落为 rollout 记录（`turn_started/turn_completed`）。

当前实现：

- Agent API 用 `while iters < max_iters` 驱动多轮工具循环。
- 每轮通过 `previous_response_id` 与上游响应串联。
- `STORAGE_MODE=none` 下会记录 `turn_index` 与 turn 状态，便于 replay 观测。

证据：

- 流式/非流式 loop：`apps/agent-api/src/anyagent_agent_api/app.py:885`、`apps/agent-api/src/anyagent_agent_api/app.py:1399`。
- turn rollout 记录入口：`apps/agent-api/src/anyagent_agent_api/app.py:343`、`apps/agent-api/src/anyagent_agent_api/storage/rollout.py:156`。

## 2.6 Item（Turn 内最小内容单元）

定义：

- 对照 Codex 的 Item，anyagent 当前最接近的是 OpenAI Responses `output item` 与 `function_call_output`。
- Item 当前不是独立存储表；在 `STORAGE_MODE=none` 下以 rollout 的 `item_observed` 记录保留最小可回放语义（脱敏摘要）。

当前实现：

- 通过 `response.output` 列表解析 `function_call` 项。
- 工具执行结果回灌为 `function_call_output` 作为下一轮输入 item。
- SSE 事件类型中已有 `response.output_item.*` 语义。
- `STORAGE_MODE=none` 下会把 function_call item 记录为 `item_observed`（含 `item_id/payload_sha256`）。

证据：

- output item 解析：`apps/agent-api/src/anyagent_agent_api/app.py:156`。
- 回灌 item 构造：`apps/agent-api/src/anyagent_agent_api/app.py:1339`。
- item rollout 记录入口：`apps/agent-api/src/anyagent_agent_api/app.py:371`、`apps/agent-api/src/anyagent_agent_api/storage/rollout.py:210`。
- output_item 事件语义：`requirements.md:356`。

## 2.7 Tool 与 Tool Call（能力面与执行面）

定义：

- Tool：对模型披露的 function tool 定义（`name/description/parameters`）。
- Tool Call：模型在某个 turn 中发起的一次具体调用（`tool_call_id + tool_name + arguments`）。

当前实现：

- Agent API 先向 Tool Runtime 拉 `manifest` 决定可见工具集合。
- Tool Runtime execute 按 `response_id:tool_call_id:tool_name` 幂等。
- Multi-Agent system tools 目前在 Agent API 内部执行，不经过 Tool Runtime。
- `STORAGE_MODE=none` 下会记录 `tool_call_requested/tool_call_completed`，默认只保存参数/输出摘要（hash+长度+预览）。

证据：

- manifest 拉取与注入：`apps/agent-api/src/anyagent_agent_api/app.py:471`、`apps/agent-api/src/anyagent_agent_api/app.py:513`。
- execute 协议字段：`packages/anyagent/src/anyagent/protocol/tool_runtime.py:86`。
- execute 幂等键：`apps/tool-runtime/src/anyagent_tool_runtime/http/app.py:209`。
- tool_call rollout 记录入口：`apps/agent-api/src/anyagent_agent_api/app.py:390`, `apps/agent-api/src/anyagent_agent_api/app.py:409`, `apps/agent-api/src/anyagent_agent_api/storage/rollout.py:240`。
- system tool 执行：`apps/agent-api/src/anyagent_agent_api/app.py:595`。

## 2.8 Event（流式与重放）

定义：

- Event 是 run 内增量事件，按 `seq` 单调递增，用于 SSE 推流、补发和回放。

当前实现：

- Event Store 以 `(response_id, seq)` 存储。
- 支持按 `last_seq` 拉取与追尾流。
- `[DONE]` 为流终止标记。
- `STORAGE_MODE=none` 时，事件与 run 快照会按 `session_partition_key` 追加到本地 `rollout.jsonl`（写入路径判重，append-only）。
- `STORAGE_MODE=none` 支持 `rollout*.jsonl` 轮转（按大小/时间）与有界保留，replay 默认覆盖当前与归档文件。
- 本地支持 rollout replay CLI，按 `session_partition_key/response_id` + `last_seq` 游标回放记录。
- 已有 smoke 验收脚本覆盖 replay 与写入门控：`scripts/acceptance_rollout_replay_smoke.py`。

证据：

- 事件模型：`apps/agent-api/src/anyagent_agent_api/storage/models.py:22`。
- 事件写入递增：`apps/agent-api/src/anyagent_agent_api/storage/postgres.py:141`。
- 内部补发/追尾：`apps/agent-api/src/anyagent_agent_api/internal/events.py:43`、`apps/agent-api/src/anyagent_agent_api/internal/events.py:99`。
- 本地 rollout 写入器：`apps/agent-api/src/anyagent_agent_api/storage/rollout.py:52`。
- 本地 rollout 回放工具：`apps/agent-api/src/anyagent_agent_api/storage/rollout_replay.py:1`。
- 轮转/恢复 smoke：`scripts/acceptance_rollout_rotation_smoke.py:1`、`scripts/acceptance_session_resume_smoke.py:1`。

## 3. 关键关联键（跨层串联）

建议用以下顺序理解链路：

1. `agent_id + session_key -> session_partition_key`
2. `session_partition_key -> run(response_id)`
3. `run(response_id) -> turn(iteration)`（内存语义）
4. `turn -> item(output/function_call/function_call_output)`（协议语义）
5. `run(response_id) + tool_call_id + tool_name -> tool execute idempotency`
6. `run(response_id) -> event(seq)`（重放语义）

对应需求锚点：

- `requirements.md#req-4-3-1`（session 分片）
- `requirements.md#req-4-4`（SSE 与 response_id 一致性）
- `requirements.md#req-5-8-1`（tool execute request 字段）
- `requirements.md#req-5-13`（可观测字段）

## 4. 当前实现边界与注意点

1. Conversation 在 anyagent 当前主要由 Session 语义承载，尚无独立 `conversation_id` 实体。
2. Turn 与 Item 均为逻辑层/协议层概念，尚未成为一等持久化实体。
3. Multi-Agent Thread 与 Session 是两条正交维度：前者是协作拓扑，后者是并发分片键；不能混用。
4. Tool Runtime execute 幂等键当前包含 `tool_name`（比需求最小键更严格）。

## 5. 参考 Codex 后的优化建议

按优先级建议如下：

1. 立刻做（文档与命名收敛）：在 `requirements.md` 与架构文档中固定术语映射：`Session(=conversation boundary)`、`Multi-Agent Thread(=collab thread)`、`Turn/Item(=loop/protocol units)`，避免 `thread/session/conversation` 混称。
2. 短期做（可观测增强）：给 turn 增加显式序号（如 `turn_index`）并写入结构化日志，降低排障成本；不必先落库。
3. 中期做（重放精度增强）：定义内部 `Item` 规范化事件（至少 message/function_call/function_call_output 三类），让 replay 能按 Item 级别重建，而不只依赖原始 SSE 块；写入路径采用“写前门控一次判重”，不走“先写后校验”。
4. 中长期做（跨实例协作一致性）：若 Multi-Agent 进入生产多实例，需把 `ThreadRecord/SubmissionRecord` 从内存迁移到外置存储，并补 lease/幂等语义。

### 5.1 本轮新增约束（to-be）

- Session 需要升级为“可恢复状态容器”：快照中至少包含 `resume_cursor(last_response_id/transcript)` 与 `runtime_config`。
- 对 OpenAI Responses provider，首轮请求优先使用 `previous_response_id + 本次增量 input` 续接，而不是每次重发全量历史。
- `runtime_config` 采用“默认绑定 + 显式字段 merge 更新”语义，覆盖字段限定为：
  - `model`
  - `temperature`
  - `top_p`
  - `frequency_penalty`
  - `presence_penalty`
  - `reasoning`
