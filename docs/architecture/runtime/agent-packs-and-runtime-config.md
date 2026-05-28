<!--
---
doc_kind: architecture
status: stable
tags: ["agent-packs", "agents-md", "agent-spec", "session", "runtime-config"]
summary: Agent Packs、AGENTS.md 注入、AgentSpec、agent_id 路由与 session runtime config 的稳定约束。
req: ["requirements.md#req-2-1", "requirements.md#req-2-1-1", "requirements.md#req-2-2", "requirements.md#req-4-3-1", "requirements.md#req-4-6"]
---
-->

# Agent Packs 与 Runtime Config

本文承接原 `requirements.md` 中已经稳定的配置即服务设计：业务工作区通过 `.anyagent/` 声明 agent 行为、工具、skills、MCP 与多 agent 策略，Core 在边界处解析并校验，运行时只消费已知形状的数据。

## Agent Packs

公共配置根目录：

```text
<workspace_dir>/.anyagent/agents/
  <agent_id>/
    agent.yaml
    AGENTS.md
    skills/
```

约束：

- `<agent_id>` 必须满足 `[a-zA-Z0-9_.-]{1,64}`。
- `agent.yaml` 与 `AGENTS.md` 为必需文件；缺失或不可解析时服务启动 fail-fast。
- 同一个 `agent_id` 只能定义一次；重复定义 fail-fast。
- v0 先冻结为 repo workspace root：`<workspace_dir>/.anyagent/agents/`。更多 roots 可以作为后续增强，但必须记录 root/path 以便审计。

## AGENTS.md 注入语义

AgentRuntime 在每次 run 初始化 prompt 时，必须把 agent pack 的 `AGENTS.md` 作为配置侧指令注入模型上下文。

要求：

- 注入发生在本次 run 的第一条 user 输入之前。
- 推荐映射为 `developer` message；不支持 `developer` role 的 provider 可退化为独立 system block。
- 注入内容必须带来源标记，至少包含 `agent_id`、path 与 hash。
- v0 使用 `workspace + agent-pack` 两层 stack：`<workspace_dir>/AGENTS.md` 为低优先级全局层，`<workspace_dir>/.anyagent/agents/<agent_id>/AGENTS.md` 为高优先级 agent 层。
- 多智能体 child thread 按目标 `agent_id` 注入对应 `AGENTS.md`，默认不继承父 thread 的 `AGENTS.md`。
- `AGENTS.md` 只影响模型推理与行为偏好，不作为 tool policy 或权限来源。
- 读取必须有硬性大小上限；超限 fail-fast，错误中包含 `agent_id/path/bytes`。
- run 记录应包含 `agent_id` 与注入文件 hash，避免配置漂移不可复盘。

## AgentSpec agent.yaml 最小 Schema

`agent.yaml` 定义该 agent 的配置集合。v0 最小字段：

```yaml
exposed: true
tools:
  requested_tool_names: ["core.web_fetch", "app.*"]
  policy:
    allow_tools: ["core.*", "app.*"]
    deny_tools: ["exec"]
skills:
  default_selected: ["repo-helper"]
  disabled_paths: []
multiagent:
  spawn_allow_agent_ids: ["researcher", "coder"]
  limits:
    max_depth: 2
    max_threads: 4
    run_timeout_seconds: 300
```

语义：

- `exposed=true`：允许外部 `POST /v1/responses` 通过 `metadata.agent_id=<agent_id>` 选择。
- `exposed=false`：不允许外部直连，只允许被 spawn 或内部受控调用。
- `tools.requested_tool_names` 是“希望披露”的工具名或 glob 集合，最终仍由 Tool Runtime manifest 收口。
- `tools.policy` 只能由服务端配置生成，外部请求的 `metadata.context.policy` 必须忽略。
- `skills.default_selected` 支持 skill name 或 `skill://.../SKILL.md` path 引用。
- `skills.disabled_paths` 配置时填写 skill name，运行时解析为当前可见 skill 的 stable id。
- `multiagent.spawn_allow_agent_ids` 缺省为空，表示禁止 spawn。

## agent_id 选择与隔离

`agent_id` 来源优先级：

1. `metadata.agent_id`
2. 受控内部 header：`x-agent-id`
3. 可选 `model` 约定：`agent:<agent_id>`
4. 默认：`main`

选择规则：

- `agent_id` 必须存在于 Agent Catalog。
- 外部直连只能选择 `AgentSpec.exposed=true` 的 agent。
- 服务启动时校验默认 `main` 存在且 `exposed=true`。
- 会话分片键固定为 `session_partition_key = "{agent_id}::{session_key}"`。

这样同一平台 thread 被多个 agent 使用时不会抢占同一把 session lock；同一 agent 内仍保持会话内串行、跨会话并行。

## Session Resume 与 runtime_config

连续会话必须从 Session Store 或本地持久化快照恢复，不依赖进程内存。

### 跨请求上下文恢复

会话快照至少包含一种恢复游标：

- `last_response_id`：优先，适用于 OpenAI Responses provider。
- 可重放 transcript/items：上游不支持 `previous_response_id` 时的兜底。

首轮上游请求组装：

- 有 `last_response_id`：使用 `previous_response_id=<last_response_id>` + 当前 `request_delta_input`。
- 无 `last_response_id` 但有 transcript：使用 `snapshot_transcript + request_delta_input`。
- 无快照：按新会话处理。

run 完成后写回新的恢复游标，保证下一次请求可继续承接。

### runtime_config 绑定与 merge 更新

受管字段集合：

- `model`
- `temperature`
- `top_p`
- `frequency_penalty`
- `presence_penalty`
- `reasoning`

规则：

- 会话首次请求初始化 `runtime_config`。
- 后续请求默认复用会话中的 `runtime_config`。
- 仅调用方显式提供字段时才做字段级覆盖。
- 同一个 run 内后续 tool 回合必须沿用同一个 `effective_runtime_config`。
- run 终态提交时将最终 `effective_runtime_config` 写回 Session Store。
- 更新快照必须带 CAS 或等价版本语义，防止并发覆盖造成配置回退。
