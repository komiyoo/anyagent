# Multi-Agent v0 范围与限制（Draft）

对应需求：`requirements.md#req-13-1`、`requirements.md#req-13-4`、`requirements.md#req-13-5`

本文件目标：在开始实现 `spawn_agent/send_input/wait/close_agent/resume_agent` 之前，先把 **v0 的目标/非目标/限制项** 固化，避免后续实现过程中出现不可控的语义漂移。

## 1) v0 目标（Goals）

v0 以“单实例可用 + 可治理”为先：

- 支持 Codex 风格编排原语：`spawn_agent`、`send_input`、`wait`、`close_agent`、`resume_agent`
- 子 agent 是独立 `thread_id`（避免与 AgentSpec 的 `agent_id` 混淆）
- 子 agent 的执行与父线程隔离（默认不 fork context），并遵循 tools/skills 的隔离与最小披露
- 每次编排动作都有可审计的事件与最小状态快照（至少能让 Gateway/UI 展示“子线程在做什么”）

## 2) v0 非目标（Non-goals）

v0 明确不承诺：

- 跨实例/跨数据中心的分布式一致性与“分布式 actor”语义
- 复杂的多智能体协商协议（先做编排原语 + 可治理）
- 子线程的强持久化恢复（重启后恢复到同一运行状态）
- 自动继承父线程的全部上下文 / tools / skills（默认禁止，避免权限泄漏）

## 3) v0 治理与限制（Must-have）

v0 必须实现并默认启用以下限制（Req: `requirements.md#req-13-4`）：

- `max_depth`：子 agent spawn 深度限制
  - child.depth = parent.depth + 1
  - 超限时拒绝，并返回模型可读错误（`depth_limit_reached`）
- `max_threads`：每个 parent thread 的最大 child threads 数
  - spawn 前必须 reserve slot；失败返回资源不足错误（`threads_limit_reached`）
- `timeouts`
  - `wait.timeout_ms` 必须有最小值（避免 tight polling）
  - 子线程单次 run 必须有 `run_timeout_seconds` 上限（避免资源耗尽）

建议的 v0 默认值（可配置）：

- `max_depth = 2`
- `max_threads = 8`
- `wait.timeout_ms`：最小 `10_000ms`，默认 `30_000ms`，最大 `3_600_000ms`
- `run_timeout_seconds = 600`（10 分钟）

## 4) tools / skills 隔离策略（v0 默认）

v0 默认隔离（Req: `requirements.md#req-13-5`）：

- `fork_context=false`：子线程默认不继承父线程完整历史
- 子线程目标 agent 必须显式指定（`spawn_agent.agent_id` 或 `spawn_agent.agent_type`），并受父线程 allowlist 限制（`multiagent.spawn_allow_agent_ids`）
- 子线程的 tools 与 skills 必须重新计算（不自动继承父线程已启用集合）
- 默认只暴露最小必要的 `core.*` 工具（或按策略放行），避免“跨线程权限泄漏”

## 5) 与 OpenAI SDK schema 的对齐策略

为减少调用方心智负担，v0 的函数工具 schema 优先对齐 OpenAI Responses SDK 形态：

- `tools[]` 中的 function tool 使用 `{"type":"function","name":"...","description":"...","parameters":{...},"strict":true}` 结构
- `tool_choice` 中 function tool 使用 `{"type":"function","name":"..."}` 结构

anyagent 侧：

- 调用方请求中的 `tools[]` 仅作为“工具可见性请求/提示”参考；最终上游 `tools[]` 以 Tool Runtime manifest 为准（避免手写 schema 漂移）
- 不兼容 legacy 嵌套 `{"type":"function","function":{"name":...}}` 形态：v0 起只维护一套 OpenAI SDK schema
