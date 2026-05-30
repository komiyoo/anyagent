<!--
---
doc_kind: architecture
status: stable
tags: ["multi-agent", "collab", "agent-control", "subagent"]
summary: Codex 风格 Multi-Agent 编排的目标、实体、系统工具、治理、隔离、事件与 AgentControl 边界。
req: ["requirements.md#req-13", "requirements.md#req-13-3", "requirements.md#req-13-8"]
---
-->

# Multi-Agent Collaboration

Multi-Agent 是 Phase 2+ 能力。它通过一组系统保留工具让主 agent 创建、驱动、等待和关闭子 agent，并保持独立状态、隔离边界与审计链路。

## 目标与非目标

目标：

- 子 agent 是独立 `thread_id` 或等价实体。
- 主 agent 通过 function tools 调用编排接口：`spawn_agent`、`send_input`、`wait`、`close_agent`、`resume_agent`。
- 有深度限制、最大线程数限制、超时限制。
- Gateway/UI 与审计面可观察子 agent 状态快照。

非目标：

- 不承诺跨数据中心强一致 actor 语义。
- 不承诺任意复杂多智能体协商协议。

## 核心实体

- Parent Thread：触发 spawn 的主会话/线程。
- Child Thread / SubAgent：被 spawn 的子会话/线程，拥有独立 `thread_id`。
- `agent_id`：AgentSpec 配置标识，例如 `main`、`legal`、`sales`。
- `thread_id`：Multi-Agent 编排中的运行时线程标识，不与 `agent_id` 混用。
- SessionSource：标注 thread 来源，例如 `cli`、`web`、`gateway`、`subagent.thread_spawn`。

## 系统工具

系统保留名必须走精确路由，不参与前缀路由。

### spawn_agent

创建 child thread，并可选立刻投递输入。

参数：

- `agent_id?: string`
- `agent_type?: string`，deprecated alias；与 `agent_id` 同时提供时必须一致。
- `message?: string`
- `items?: array`
- `skills?: string[]`
- `fork_context?: boolean`，默认 `false`。

返回：

- `thread_id`
- `agent_id`
- `nickname?`

### send_input

向已有 child thread 投递输入。

参数：

- `id`
- `message?`
- `items?`
- `interrupt?`

返回：`submission_id`。

### wait

等待一个或多个 child thread 到达终态或超时。

参数：

- `ids: string[]`
- `timeout_ms?`

返回：

- `agents_states`
- `timed_out`

### close_agent

关闭或回收 child thread。

### resume_agent

从持久化记录恢复 child thread。

## 治理与限制

- `max_depth`：child depth = parent depth + 1，超过拒绝。
- `max_threads`：每个 parent 或 tenant 的最大 child threads 数。
- `wait.timeout_ms`：设置最小值，避免 tight polling。
- `run_timeout_seconds`：child run 最大运行时间。

## 隔离策略

默认隔离：

- child 不继承父完整消息历史，`fork_context=false`。
- child 目标 `agent_id` 必须显式指定，并满足父 agent 的 `multiagent.spawn_allow_agent_ids`。
- child tools 重新计算，不自动披露父 thread 的平台能力工具。
- child skills 重新选择，不自动继承父已启用 skills。

该策略与 Skills 动态披露一致：不默认注入，不默认披露依赖工具。

## 事件与审计

内部事件建议：

- `collab_agent_spawn_begin`
- `collab_agent_spawn_end`
- `collab_agent_interaction_begin`
- `collab_agent_interaction_end`
- `collab_waiting_begin`
- `collab_waiting_end`
- `collab_close_begin`
- `collab_close_end`
- `collab_resume_begin`
- `collab_resume_end`

审计字段：

- `parent_thread_id`
- `child_thread_id`
- `session_key`
- `depth`
- `tool_name`
- `tool_call_id`
- 结果状态。

## 与 v1/responses 的关系

对外仍只暴露 `/v1/responses`。

- Multi-Agent 编排工具以 function tools 出现在 `tools[]` 中。
- `function_call_output.output` 返回 JSON string。
- 不建议把 collab 事件映射为 OpenAI Responses SSE 自定义事件。
- Gateway/UI 通过 anyagent 内部事件流观察 collab 事件。

## Reference Runtime Contract

当前 reference runtime 已收敛为 `task()` tool 模式。本文前半部分的 `spawn_agent` / `send_input` / `wait` / `close_agent` 是长期 AgentControl 方向；Phase 1.8 的可验收合同以 `anyagent.protocol.multi_agent` 与 `anyagent.agent_runtime.multiagent` 为准。

父 / 子 / root run 语义：

- root run 是用户直接创建的 `/v1/responses` run。
- parent run 是发起 `task()` tool call 的 run；root run 可以同时也是 parent run。
- child run 是 `SubAgentExecutor` 为单次 task 创建的子执行实例。
- child run 必须拥有独立上下文；默认 `isolated`，可通过 `fork_last_n` 继承父上下文尾部片段。
- depth 从 parent 递增，超过 `runtime.subagent.max_depth` 时不得注册或执行新的 `task()` tool。
- parent run 通过 `subagent.spawned`、`subagent.completed`、`subagent.timeout` stage events 关联 child run。
- replay 与观测链路必须保留 `parent_run_id`、`child_run_id`、`agent_id`、`depth` 与 `tool_call_id` 等稳定键。
- quota 跨节点一致性基线由 `MultiAgentQuota` 绑定到 storage `LeaseLock` contract：同一 `root_response_id` 下按 slot key 竞争租约，PostgreSQL/Redis/in-memory lock 共享同一语义。

Contract test 入口：

- `tests/unit/agent_runtime/test_multiagent_task_schema.py` 覆盖 task schema、in-process executor、并发/深度/超时和 fork mode 主路径。
- `tests/contract/test_multiagent_contract.py` 覆盖 storage lock quota 语义，以及 parent/child run 在 replay 中保留 `child_response_id` / `parent_response_id` / `tool_call_id` 的端到端 contract。
- `tests/fixtures/sdk_conformance/core_surface.json` 固化 `stage_event.subagent.spawned` / `stage_event.subagent.completed` / `stage_event.subagent.timeout` 的跨 SDK fixture。
- `tests/contract/test_protocol_schema_export.py` 校验上述 stage event fixture 被 minimum matrix 引用。

尚未承诺的 Phase 4 缺口：

- AgentControl 多线程生命周期 API 的 public protocol 形态。

## AgentControl

AgentControl 是内部控制面组件，可以与 Agent API 同部署，但逻辑上分层。

职责：

- spawn/close/resume child threads。
- 管理 child thread 状态机与资源配额。
- 提供 wait/status 订阅。

Agent API 职责：

- 在 agent loop 中执行系统工具调用。
- 将工具结果回灌给模型继续推理。
