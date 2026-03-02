# Agent API TODO

对应需求：`requirements.md#req-4`

## 目标

- 对外提供 OpenAI Responses API 兼容入口（`POST /v1/responses` + SSE），并具备最小可用的会话路由与工具调用闭环。

## 里程碑（Milestones）

- M1：`POST /v1/responses` 非流式可用（最小字段集）
- M2：SSE 流式事件可用（SDK 可消费）
- M3：工具调用闭环（与 Tool Runtime 对接）+ 基础可观测

## 任务（Tasks）

- [x] P0 定义并实现 `POST /v1/responses` 请求/响应最小兼容集（Req: `requirements.md#req-4-1`；Impl: `apps/agent-api/src/anyagent_agent_api/app.py:264`；Module: `agent-api`）
- [x] P0 实现鉴权与 `Idempotency-Key` 处理策略（Req: `requirements.md#req-4-2`；Impl: `apps/agent-api/src/anyagent_agent_api/auth.py:10`, `apps/agent-api/src/anyagent_agent_api/openai_proxy.py:37`；Module: `agent-api`）
- [x] P0 解析 `metadata.session_key` / `metadata.agent_id` 并落地 `session_partition_key` 规则（Req: `requirements.md#req-4-3`，`requirements.md#req-4-3-1`；Impl: `apps/agent-api/src/anyagent_agent_api/app.py:282`；Module: `agent-api`）
- [x] P1 实现 SSE streaming 透传（含 `[DONE]`）结束语义（Req: `requirements.md#req-4-4`；Impl: `apps/agent-api/src/anyagent_agent_api/openai_proxy.py:48`；Module: `agent-api`）
- [x] P0 安全：外部 `tools[]`/`tool_choice` 必须经 Tool Runtime `manifest` 过滤（Req: `requirements.md#req-4-5`；Impl: `apps/agent-api/src/anyagent_agent_api/app.py:370`；Module: `agent-api`）
- [x] P1 对接 Tool Runtime：manifest 拉取 + tools 注入（Req: `requirements.md#req-4-5`，`requirements.md#req-5-2`；Impl: `apps/agent-api/src/anyagent_agent_api/app.py:370`, `apps/agent-api/src/anyagent_agent_api/tool_runtime_client.py:14`；Module: `agent-api`）
- [x] P1 对接 Tool Runtime：execute 回灌 loop（仅 `stream=false`）（Req: `requirements.md#req-4-5`，`requirements.md#req-5-1`；Impl: `apps/agent-api/src/anyagent_agent_api/app.py:522`, `apps/agent-api/src/anyagent_agent_api/tool_runtime_client.py:43`；Module: `agent-api`）
- [x] P1 对接 Tool Runtime：execute 回灌 loop（支持 `stream=true` SSE）（Req: `requirements.md#req-4-4`，`requirements.md#req-4-5`；Impl: `apps/agent-api/src/anyagent_agent_api/app.py:415`, `apps/agent-api/src/anyagent_agent_api/openai_client.py:76`；Module: `agent-api`）
- [x] P0 Agent Packs：加载 `.agents/agents/<agent_id>/` 并在路由时强校验 `agent_id` 存在与 `exposed=true`（Req: `requirements.md#req-2-1`，`requirements.md#req-2-2`，`requirements.md#req-4-3-1`；Impl: `packages/anyagent/src/anyagent/agent_packs.py:122`, `apps/agent-api/src/anyagent_agent_api/app.py:205`；Module: `agent-api`）
- [x] P0 Agent Packs：注入 `<agent_pack>/AGENTS.md`（developer message）+ 工具策略由服务端生成（忽略 caller policy）（Req: `requirements.md#req-2-1-1`，`requirements.md#req-2-2`；Impl: `apps/agent-api/src/anyagent_agent_api/app.py:348`, `apps/agent-api/src/anyagent_agent_api/app.py:399`；Module: `agent-api`）
- [x] P1 Skills：支持 agent 私有 skills root + AgentSpec `default_selected` + skills 注入 + dependencies->requested_tool_names（Req: `requirements.md#req-12-2`，`requirements.md#req-12-6-1`，`requirements.md#req-12-6-2`，`requirements.md#req-12-6-3`；Impl: `apps/agent-api/src/anyagent_agent_api/app.py:309`, `packages/anyagent/src/anyagent/skills/selection.py:135`；Module: `agent-api`）
- [x] P1 实现 Tool Runtime manifest 缓存（短 TTL + cache key 设计）（Req: `requirements.md#req-5-2-2`；Impl: `apps/agent-api/src/anyagent_agent_api/manifest_cache.py:18`；Module: `agent-api`）
- [x] P1 处理 `toolset_version_mismatch`：刷新 manifest 并对单次 tool call 重试 1 次（Req: `requirements.md#req-5-1`，`requirements.md#req-5-2-2`；Impl: `apps/agent-api/src/anyagent_agent_api/app.py:458`；Module: `agent-api`）

## 决策 & 争议点

- [ ] Agent API 对外暴露哪些 “可选增强” endpoint（查询/取消）在 v0 是否实现（Req: `requirements.md#req-4-1`）
