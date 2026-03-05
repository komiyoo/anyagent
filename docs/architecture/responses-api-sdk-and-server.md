<!--
Single Source of Truth:
- External API contract: requirements.md#req-4 (Responses API) / requirements.md#req-4-4 (SSE)
- This doc focuses on swimlanes + module boundaries (how we wire it in code).
-->

# Responses API：SDK 接入与 Agent Server（anyagent）

目标：让 **接入侧（Agent SDK）** 与 **服务侧（Agent Server）** 都围绕 OpenAI **Responses API**（`POST /v1/responses` + SSE）形成一个稳定、可复用、类型清晰的接口面。

## 1) 关键约定

- **对外协议 SSOT**：`requirements.md#req-4`（Responses API）与 `requirements.md#req-4-4`（SSE）
- **服务侧**：anyagent Agent API 对外暴露 `POST /v1/responses`
- **接入侧**：优先使用 OpenAI 官方 SDK 的 Responses API 能力（类型/模型由官方维护），anyagent 提供 _Factory/Singleton_ 负责配置与复用

## 2) 泳道（Swimlane）视角

```mermaid
sequenceDiagram
  autonumber
  participant App as App / Gateway / Client
  participant SDK as anyagent AgentRuntime ModelProvider
  participant OA as OpenAI Official SDK (Responses)
  participant AS as anyagent Agent Server (Agent API)
  participant ST as Storage (Run/Event)
  participant TR as Tool Runtime
  participant UO as Upstream OpenAI (optional)

  App->>SDK: get_default_model_provider()
  SDK-->>App: OpenAIResponsesModelProvider(base_url=AgentServer/v1)

  App->>SDK: create_response(stream=true, ...)
  SDK->>OA: responses.create(stream=true, ...)
  OA->>AS: POST /v1/responses (SSE)
  AS->>ST: append events / set run final
  AS->>TR: /internal/tools/manifest|execute (when tool calls)
  TR-->>AS: tool output
  AS-->>OA: SSE events + [DONE]
  OA-->>SDK: streaming events
  SDK-->>App: streaming events

  Note over AS,UO: 作为代理/编排器时，AS 也可调用上游 OpenAI Responses API
```

## 3) 模块边界（Pattern）

- **Factory**：`anyagent.agent_runtime.model_providers` 提供 `create_openai_responses_model_provider()`
- **Singleton**：`anyagent.agent_runtime.model_providers` 提供 `get_default_model_provider()`（避免重复初始化 SDK client）
- **协议工具 SSOT**：SSE 解析/编码在 `anyagent.protocol.sse` 收敛（供 SDK/Server 复用）

## 4) Client SDK（anyagent Python）— 资源型命名空间

anyagent Client SDK 采用**资源型命名空间**模式，以 `AnyAgent` 为入口，通过子命名空间组织能力（设计决策见 `docs/architecture/decisions/openai-first-api-surface.md`）：

```python
client = AnyAgent(api_key=”...”, base_url=”http://127.0.0.1:8787”)

# ── OpenAI 兼容面（responses 命名空间委托 OpenAI 官方 SDK）──
client.responses.create(...)              # POST /v1/responses
client.responses.retrieve(response_id)    # GET /v1/responses/{id}
client.responses.cancel(response_id)      # POST /v1/responses/{id}/cancel

# ── AnyAgent 超集面 ──
client.events.list(response_id)           # GET /internal/events/list
client.events.stream(response_id)         # GET /internal/events/stream → SSEBlock
client.events.stream_typed(response_id)   # → StageEvent typed union

client.skills.list(agent_id=”main”)       # GET /internal/skills/list

# ── 便捷方法：直接获取 OpenAI 官方 SDK client ──
client.as_openai_client()                 # → openai.OpenAI
client.as_async_openai_client()           # → openai.AsyncOpenAI
```

设计要点：

- `responses` 命名空间**委托 OpenAI 官方 SDK**（Responses API typed models 由官方维护），不重复封装 HTTP 调用
- `events` / `skills` 命名空间承载 anyagent 专有 internal endpoints
- 每个子命名空间是轻量类，共享 `_http` / `_base_url` / `_api_key` 引用
- `/internal/events/stream` 的 SSE `id:` 字段承载事件 `seq`（Event Store 序号），SDK 映射为 `StageEvent.seq`，便于断线续传与 replay
- 若希望获得 tool/command 粒度的阶段性事件（stage events），见：`docs/architecture/agent-api-client-stage-events.md`
- 入口模块：`packages/anyagent/src/anyagent/agent_api_client.py`
