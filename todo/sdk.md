# SDK TODO

对应需求：`requirements.md#req-4`

## 目标

- 接入侧（SDK）统一使用 OpenAI Responses API（优先 OpenAI 官方 SDK 类型/模型）。
- 服务侧（anyagent Agent Server / Agent API）对外提供 Responses API（`POST /v1/responses` + SSE）。
- 数据模型/协议/类型注释优先，尽量收敛单一真源（SSOT）。

## 任务（Tasks）

- [x] P0 收敛 SSE 协议工具为单一真源（Req: `requirements.md#req-4-4`；Impl: `packages/anyagent/src/anyagent/protocol/sse.py:1`；Module: `protocol`）
- [x] P0 提供 OpenAI Responses ModelProvider（Factory/Singleton）（Req: `requirements.md#req-4`；Impl: `packages/anyagent/src/anyagent/agent_runtime/model_providers/openai_responses.py:1`；Module: `agent_runtime`）
- [x] P0 补齐 function tool schema（Tool Runtime manifest SSOT）（Req: `requirements.md#req-4-5`；Impl: `packages/anyagent/src/anyagent/protocol/openai_responses.py:18`；Module: `protocol`）
- [x] P0 复用 OpenAI SDK Response/StreamEvent schema 作为强类型提示（Req: `requirements.md#req-4-4`；Impl: `packages/anyagent/src/anyagent/protocol/openai_responses.py:45`；Module: `protocol`）
- [x] P1 补齐接入侧/服务侧泳道与模块边界文档（Req: `requirements.md#req-4`；Impl: `docs/architecture/responses-api-sdk-and-server.md:1`；Module: `docs`）
