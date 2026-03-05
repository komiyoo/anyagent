# Multi-Agent 与 `/v1/responses` 兼容性注意事项（Draft）

对应需求：`requirements.md#req-13-7`

本文件目标：明确 anyagent multi-agent 系统工具（`spawn_agent/send_input/wait/close_agent/resume_agent`）在 **OpenAI Responses API** 语义下的表现与限制，避免调用方（Gateway/UI/SDK）产生错误预期。

## 1) 对外唯一入口：仍然是 `/v1/responses`

- anyagent 对外只暴露 `/v1/responses`（以及少量 `/internal/*` 调试端点）。
- multi-agent 的“编排能力”以 function tools 的形式对模型可见：
  - system tools 会被追加到本次 run 的 `tools[]`（由 Agent API 注入）
  - tool call 以 `output[].type == "function_call"` 的形式出现

## 2) 工具 schema：统一使用 OpenAI Responses 的 function tool 形态

- `tools[]`：
  - `{"type":"function","name":"...","description":"...","parameters":{...},"strict":true}`
- `tool_choice`（function）：
  - `{"type":"function","name":"..."}`

约束：

- anyagent v0 起只维护一套 canonical schema；不兼容 legacy 嵌套形态（例如 `{"type":"function","function":{"name":...}}`）。

## 3) 工具输出：`function_call_output.output` 建议为 JSON string

multi-agent 系统工具返回值会回灌为 `function_call_output`：

- `spawn_agent`：`{"thread_id":"...","agent_id":"...","nickname":null}`
- `send_input`：`{"submission_id":"..."}`
- `wait`：`{"agents_states":{...},"timed_out":false}`
- `close_agent` / `resume_agent`：`{"ok":true|false}`

注意：

- output 为 **string**（JSON 文本），便于模型侧读取与二次加工。

## 4) Streaming 行为：不扩展 OpenAI SSE 事件类型

- 对外 streaming 仍然只输出标准 OpenAI Responses SSE 事件。
- anyagent 不会把 collab/multi-agent 事件映射成自定义 SSE event（避免 SDK 不兼容）。

内部审计：

- multi-agent 的 begin/end 事件通过 Agent API 的结构化日志输出（`collab_*_begin/end`），用于 Gateway/UI 后续接入内部事件流或审计系统。

## 5) v0 限制：child thread 不自动执行

当前 v0 实现的重点是“系统工具契约 + 治理边界”：

- `spawn_agent` 只创建 child thread 记录并返回 `thread_id`
- `send_input` 只记录一次 submission（返回 `submission_id`）
- `wait` 仅基于 thread 状态快照等待（不会驱动真实执行）

因此：

- v0 不会产生“子 agent 的模型输出内容”回灌给父 agent；后续需要引入 AgentControl/Runner（见 `requirements.md#req-13-8`）。

## 6) 最小验证（建议）

1. 启动 Agent API（示例）：
   - `cd apps/agent-api && uv run agent-api`
2. 触发一次 run，让模型调用 `spawn_agent` 并拿到 `thread_id`
3. 继续同一个 response loop 内调用 `send_input` / `wait` / `close_agent`
4. 观察 Agent API 日志中是否出现：
   - `collab_agent_spawn_begin/end`
   - `collab_agent_interaction_begin/end`
   - `collab_waiting_begin/end`
   - `collab_close_begin/end`
