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
- [x] P0 增强 SDK tool loop：支持 MCP manifest 合并与 `mcp.` 执行分流（Req: `requirements.md#req-4-5`，`requirements.md#req-12-4`；Impl: `packages/anyagent/src/anyagent/agent_runtime/tool_loop.py:103`；Module: `agent_runtime`）
  - refs: `packages/anyagent/src/anyagent/agent_runtime/tool_loop.py:216`
- [x] P1 收敛文档信息架构：补充 apps/packages 职责边界与 demo 定制化实操手册（Req: `requirements.md#req-4`，`requirements.md#req-2-1`；Impl: `docs/architecture/apps-packages-boundary.md:1`；Module: `docs`）
  - refs: `docs/acceptance/acceptance-demo-customization.md:1`
- [x] P1 收敛 OpenAI Responses 公共 helper：`tool_choice` 校验、`function_call` 提取、tool arguments 解析由 `anyagent.protocol.openai_responses` 提供单一实现（Req: `requirements.md#req-4-4`，`requirements.md#req-4-5`；Impl: `packages/anyagent/src/anyagent/protocol/openai_responses.py:46`；Module: `protocol`）
- [x] P1 收敛 Responses body 注入 helper：skills 注入与 Agent Pack 注入共用同一实现（Req: `requirements.md#req-2-1-1`，`requirements.md#req-12-6-2`；Impl: `packages/anyagent/src/anyagent/protocol/openai_responses.py:105`；Module: `protocol/agent_runtime`）
  - refs: `packages/anyagent/src/anyagent/agent_runtime/skills_injection.py:45`
- [x] P1 收敛 tool-loop follow-up payload helper：SDK runtime 与 Agent API 共用下一轮 body 构造与工具白名单提取（Req: `requirements.md#req-4-5`；Impl: `packages/anyagent/src/anyagent/agent_runtime/tool_loop_payloads.py:1`；Module: `agent_runtime`）
  - refs: `packages/anyagent/src/anyagent/agent_runtime/tool_loop.py:131`
  - refs: `apps/agent-api/src/anyagent_agent_api/app.py:1742`
- [x] P1 收敛 tool result helper：SDK 提供统一的工具执行结果归一化与 `function_call_output` 组装，应用层仅复用（Req: `requirements.md#req-4-5`，`requirements.md#req-5-1`；Impl: `packages/anyagent/src/anyagent/agent_runtime/tool_results.py:1`；Module: `agent_runtime`）
  - refs: `packages/anyagent/src/anyagent/agent_runtime/tool_loop.py:180`
  - refs: `apps/agent-api/src/anyagent_agent_api/app.py:1445`
- [x] P1 AnyAgent Client SDK 资源型命名空间设计（`AnyAgent` 入口 + `responses`/`events`/`skills` 子命名空间），`responses` 委托 OpenAI 官方 SDK（Req: `requirements.md#req-4-1`；Impl: `packages/anyagent/src/anyagent/agent_api_client.py:267`；Module: `sdk`）
  - refs: `packages/anyagent/src/anyagent/agent_api_client.py:101`（Responses）
  - refs: `packages/anyagent/src/anyagent/agent_api_client.py:130`（Events）
  - refs: `packages/anyagent/src/anyagent/agent_api_client.py:254`（Skills）
  - refs: `packages/anyagent/src/anyagent/__init__.py:1`（公共导出）
  - refs: `docs/architecture/decisions/openai-first-api-surface.md:1`
