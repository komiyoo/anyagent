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
from anyagent import AnyAgent

client = AnyAgent(api_key="...", base_url="http://127.0.0.1:8787")

# ── OpenAI 兼容面（优先使用 OpenAI 官方 SDK）──
# sync
oa = client.openai                        # → 缓存的 openai.OpenAI(base_url=.../v1)
resp = oa.responses.create(...)           # POST /v1/responses
resp2 = oa.responses.retrieve(resp.id)    # GET /v1/responses/{id}

# async
oaa = client.async_openai                 # → 缓存的 openai.AsyncOpenAI(base_url=.../v1)
resp3 = await oaa.responses.create(...)   # POST /v1/responses

# ── 可选增强：AnyAgent response async helpers（返回 OpenAI-compatible Response payload）──
payload = await client.responses.retrieve(resp.id)    # GET /v1/responses/{id}
payload2 = await client.responses.cancel(resp.id)     # POST /v1/responses/{id}/cancel

# ── AnyAgent 超集面（internal endpoints）──
events = await client.events.list(resp.id)            # GET /internal/events/list
async for ev in client.events.stream_typed(resp.id):  # GET /internal/events/stream → StageEvent
    ...

skills = await client.skills.list(agent_id="main")    # GET /internal/skills/list
```

设计要点：

- `AnyAgent` 维持单一入口类；不额外拆 `AnyAgentSync` / `AsyncAnyAgent`，避免 sync/async 两套命名空间长期漂移
- `client.openai` / `client.async_openai` 是主入口：缓存 OpenAI 官方 SDK client，承载 `responses.create/stream/retrieve/cancel`
- `as_openai_client()` / `as_async_openai_client()` 保留为显式工厂，用于调用方需要全新 SDK client 实例的场景
- `client.responses.*` 只保留 AnyAgent 自己补充的 async helper（`retrieve/cancel/retrieve_typed`），避免复制 `create/stream` 等 fast-moving 官方 SDK 能力
- 可选增强 endpoint（`GET/POST /v1/responses/{id}`）用于兼容 OpenAI SDK 的 `responses.retrieve/cancel`
- `events` / `skills` 命名空间承载 anyagent 专有 internal endpoints
- 每个子命名空间是轻量类，共享 `_http` / `_base_url` / `_api_key` 引用
- `/internal/events/stream` 的 SSE `id:` 字段承载事件 `seq`（Event Store 序号），SDK 映射为 `StageEvent.seq`，便于断线续传与 replay
- 若希望获得 tool/command 粒度的阶段性事件（stage events），见：`docs/architecture/agent-api-client-stage-events.md`
- 入口模块：`packages/anyagent/src/anyagent/agent_api_client.py`
