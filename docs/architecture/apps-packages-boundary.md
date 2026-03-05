# apps / packages 边界与收敛策略（v0）

对应需求：`requirements.md#req-4`、`requirements.md#req-5`、`requirements.md#req-12`

## 1. 目标

本文件用于收敛 anyagent 仓库中的模块职责，避免“服务实现”和“共享 SDK/协议”重复演化，确保：

- 对外协议与内部协议均有单一真源（SSOT）
- `apps/*` 作为 demo/部署入口，突出编排与定制能力
- `packages/anyagent/*` 作为可复用能力层，减少跨服务重复代码

## 2. 职责边界（必须遵守）

### `packages/anyagent/*`（共享能力层）

- 协议模型（`anyagent.protocol.*`）
- 共享运行时 primitives（tool registry/client、session key、skills 选择与注入）
- SDK/CLI 能力（供外部项目或 app 复用）

示例：

- Tool Runtime 协议模型：`packages/anyagent/src/anyagent/protocol/tool_runtime.py`
- SSE 协议工具：`packages/anyagent/src/anyagent/protocol/sse.py`
- Skills 选择与权限：`packages/anyagent/src/anyagent/skills/*`

### `apps/*`（服务编排层 / demo 应用层）

- HTTP 路由与鉴权
- 存储、并发控制、可观测事件写入
- 将 Agent Packs / Skills / Tool Runtime / Model Provider 编排成完整业务流程

示例：

- Agent API 对外接口与会话编排：`apps/agent-api/src/anyagent_agent_api/app.py`
- Tool Runtime 执行路由与审计：`apps/tool-runtime/src/anyagent_tool_runtime/http/app.py`

## 3. 收敛策略（Protocol-First）

新增或修改任一可消费协议（HTTP payload / SSE event / internal model）时：

1. 先更新 `anyagent.protocol.*` 模型（SSOT）。
2. `apps/*` 仅复用该模型，不重复定义同构结构。
3. 若历史路径已被 app 内部引用，允许保留“兼容 re-export 模块”，但禁止再引入新字段分叉。

## 4. 当前已收敛项（2026-03-05）

- Tool Runtime HTTP 入参/出参模型由 app 本地定义收敛为复用协议模型：
  - `apps/tool-runtime/src/anyagent_tool_runtime/http/api_models.py`
  - SSOT：`packages/anyagent/src/anyagent/protocol/tool_runtime.py`
- Agent API -> Tool Runtime 的 manifest/execute 请求体构造改为 shared typed model（减少手写 payload 分叉）：
  - `apps/agent-api/src/anyagent_agent_api/clients/tool_runtime_client.py`
- OpenAI Responses tool-loop 公共 helper（`tool_choice` 校验、`function_call` 提取、arguments 解析）下沉到 protocol 层复用：
  - `packages/anyagent/src/anyagent/protocol/openai_responses.py`
  - 消费方：`apps/agent-api/src/anyagent_agent_api/app.py`、`packages/anyagent/src/anyagent/agent_runtime/tool_loop.py`
- Tool-loop follow-up payload 构造与工具名白名单提取下沉到 `agent_runtime`：
  - `packages/anyagent/src/anyagent/agent_runtime/tool_loop_payloads.py`
  - 消费方：`apps/agent-api/src/anyagent_agent_api/app.py`、`packages/anyagent/src/anyagent/agent_runtime/tool_loop.py`
- 工具执行结果标准化（错误结构、`function_call_output` 序列化）下沉到 `agent_runtime`：
  - `packages/anyagent/src/anyagent/agent_runtime/tool_results.py`
  - 消费方：`apps/agent-api/src/anyagent_agent_api/app.py`、`packages/anyagent/src/anyagent/agent_runtime/tool_loop.py`
- `response.completed` 事件 payload 解码收敛到 protocol helper，避免 app 内重复定义：
  - `packages/anyagent/src/anyagent/protocol/openai_responses.py`
  - 消费方：`apps/agent-api/src/anyagent_agent_api/app.py`

## 5. 允许的“非重复”差异

以下差异属于“编排层特化”，不是重复实现：

- Agent API 的 session snapshot / replay / multi-agent system tool 编排
- Tool Runtime 的执行器、凭证注入、审计日志策略
- 与部署形态绑定的设置项与服务级异常映射

这类能力可以保留在 `apps/*`，但其输入/输出协议模型仍必须复用 `packages`。

## 6. 设计模式与文件层级建议

### 分层模式（推荐）

- `protocol/*`：Wire-level contract（请求/响应/SSE/字段校验/轻量 payload helper）
- `agent_runtime/*`：运行时编排 primitives（manifest/tool-loop/session runtime/prompt 组装）
- `apps/*`：HTTP orchestration（鉴权、存储、并发控制、落库与审计）

### 文件层级收敛准则

- 协议形态相关工具（例如 `tool_choice` 校验、`function_call` 提取、body 注入）优先放在 `anyagent.protocol.openai_responses`。
- 与会话状态绑定的纯函数（runtime config merge、session snapshot build/resume）放在 `anyagent.agent_runtime.session_runtime`。
- 业务提示拼接类逻辑（Agent Pack 注入文本）放在 `anyagent.agent_runtime.prompt_injection`，避免塞进 `app.py`。
- 工具执行结果归一化（`status/error/output` 与 `function_call_output` 组装）放在 `anyagent.agent_runtime.tool_results`，应用层只做编排与审计。

### 模式收益

- 减少“同一规则在 app + sdk + runtime 三处重复实现”的漂移风险。
- `app.py` 保持 orchestration 角色，方便后续拆分 controller/flow。
- 未来做多服务/多 SDK 时，复用路径与责任边界更稳定。
