# Agent API TODO

对应需求：`requirements.md#req-4`

## 目标

- 对外提供 OpenAI Responses API 兼容入口（`POST /v1/responses` + SSE），并具备最小可用的会话路由与工具调用闭环。

## 里程碑（Milestones）

- M1：`POST /v1/responses` 非流式可用（最小字段集）
- M2：SSE 流式事件可用（SDK 可消费）
- M3：工具调用闭环（与 Tool Runtime 对接）+ 基础可观测

## 任务（Tasks）

- [x] P0 定义并实现 `POST /v1/responses` 请求/响应最小兼容集（Req: `requirements.md#req-4-1`；Impl: `apps/agent-api-py/src/anyagent_agent_api/app.py:61`；Module: `agent-api`）
- [x] P0 实现鉴权与 `Idempotency-Key` 处理策略（Req: `requirements.md#req-4-2`；Impl: `apps/agent-api-py/src/anyagent_agent_api/auth.py:10`, `apps/agent-api-py/src/anyagent_agent_api/openai_proxy.py:37`；Module: `agent-api`）
- [x] P0 解析 `metadata.session_key` / `metadata.agent_id` 并落地 `session_partition_key` 规则（Req: `requirements.md#req-4-3`，`requirements.md#req-4-3-1`；Impl: `apps/agent-api-py/src/anyagent_agent_api/app.py:79`；Module: `agent-api`）
- [x] P1 实现 SSE streaming 透传（含 `[DONE]`）结束语义（Req: `requirements.md#req-4-4`；Impl: `apps/agent-api-py/src/anyagent_agent_api/openai_proxy.py:48`；Module: `agent-api`）
- [ ] P1 对接 Tool Runtime：工具 manifest 拉取 + execute 回灌 loop（Req: `requirements.md#req-4-5`）

## 决策 & 争议点

- [ ] Agent API 对外暴露哪些 “可选增强” endpoint（查询/取消）在 v0 是否实现（Req: `requirements.md#req-4-1`）
