<!--
Single Source of Truth:
- External API contract: requirements.md#req-4 (Responses API) / requirements.md#req-4-4 (SSE)
- This doc focuses on swimlanes + module boundaries (how we wire it in code).
-->

# Responses API：SDK 接入与 Agent Server（AnyAgent）

目标：让 **接入侧（Agent SDK）** 与 **服务侧（Agent Server）** 都围绕 OpenAI **Responses API**（`POST /v1/responses` + SSE）形成一个稳定、可复用、类型清晰的接口面。

## 1) 关键约定

- **对外协议 SSOT**：`requirements.md#req-4`（Responses API）与 `requirements.md#req-4-4`（SSE）
- **服务侧**：AnyAgent Agent API 对外暴露 `POST /v1/responses`
- **接入侧**：优先使用 OpenAI 官方 SDK 的 Responses API 能力（类型/模型由官方维护），AnyAgent 提供 *Factory/Singleton* 负责配置与复用

## 2) 泳道（Swimlane）视角

```mermaid
sequenceDiagram
  autonumber
  participant App as App / Gateway / Client
  participant SDK as AnyAgent AgentRuntime ModelProvider
  participant OA as OpenAI Official SDK (Responses)
  participant AS as AnyAgent Agent Server (Agent API)
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
