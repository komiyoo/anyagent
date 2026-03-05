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
- [x] P0 实现鉴权与 `Idempotency-Key` 处理策略（Req: `requirements.md#req-4-2`；Impl: `apps/agent-api/src/anyagent_agent_api/auth.py:10`, `apps/agent-api/src/anyagent_agent_api/clients/openai_proxy.py:37`；Module: `agent-api`）
- [x] P0 解析 `metadata.session_key` / `metadata.agent_id` 并落地 `session_partition_key` 规则（Req: `requirements.md#req-4-3`，`requirements.md#req-4-3-1`；Impl: `apps/agent-api/src/anyagent_agent_api/app.py:282`；Module: `agent-api`）
- [x] P1 实现 SSE streaming 透传（含 `[DONE]`）结束语义（Req: `requirements.md#req-4-4`；Impl: `apps/agent-api/src/anyagent_agent_api/clients/openai_proxy.py:48`；Module: `agent-api`）
- [x] P0 安全：外部 `tools[]`/`tool_choice` 必须经 Tool Runtime `manifest` 过滤（Req: `requirements.md#req-4-5`；Impl: `apps/agent-api/src/anyagent_agent_api/app.py:370`；Module: `agent-api`）
- [x] P1 对接 Tool Runtime：manifest 拉取 + tools 注入（Req: `requirements.md#req-4-5`，`requirements.md#req-5-2`；Impl: `apps/agent-api/src/anyagent_agent_api/app.py:370`, `apps/agent-api/src/anyagent_agent_api/clients/tool_runtime_client.py:20`；Module: `agent-api`）
- [x] P1 对接 Tool Runtime：execute 回灌 loop（仅 `stream=false`）（Req: `requirements.md#req-4-5`，`requirements.md#req-5-1`；Impl: `apps/agent-api/src/anyagent_agent_api/app.py:522`, `apps/agent-api/src/anyagent_agent_api/clients/tool_runtime_client.py:48`；Module: `agent-api`）
- [x] P1 对接 Tool Runtime：execute 回灌 loop（支持 `stream=true` SSE）（Req: `requirements.md#req-4-4`，`requirements.md#req-4-5`；Impl: `apps/agent-api/src/anyagent_agent_api/app.py:415`, `apps/agent-api/src/anyagent_agent_api/clients/openai_client.py:12`；Module: `agent-api`）
- [x] P0 Agent Packs：加载 `.agents/agents/<agent_id>/` 并在路由时强校验 `agent_id` 存在与 `exposed=true`（Req: `requirements.md#req-2-1`，`requirements.md#req-2-2`，`requirements.md#req-4-3-1`；Impl: `packages/anyagent/src/anyagent/agent_packs.py:122`, `apps/agent-api/src/anyagent_agent_api/app.py:205`；Module: `agent-api`）
- [x] P0 Agent Packs：注入 `<agent_pack>/AGENTS.md`（developer message）+ 工具策略由服务端生成（忽略 caller policy）（Req: `requirements.md#req-2-1-1`，`requirements.md#req-2-2`；Impl: `apps/agent-api/src/anyagent_agent_api/app.py:348`, `apps/agent-api/src/anyagent_agent_api/app.py:399`；Module: `agent-api`）
- [x] P1 Skills：支持 agent 私有 skills root + AgentSpec `default_selected` + skills 注入 + dependencies->requested_tool_names（Req: `requirements.md#req-12-2`，`requirements.md#req-12-6-1`，`requirements.md#req-12-6-2`，`requirements.md#req-12-6-3`；Impl: `apps/agent-api/src/anyagent_agent_api/app.py:309`, `packages/anyagent/src/anyagent/skills/selection.py:135`；Module: `agent-api`）
- [x] P1 实现 Tool Runtime manifest 缓存（短 TTL + cache key 设计）（Req: `requirements.md#req-5-2-2`；Impl: `apps/agent-api/src/anyagent_agent_api/manifest_cache.py:18`；Module: `agent-api`）
- [x] P1 处理 `toolset_version_mismatch`：刷新 manifest 并对单次 tool call 重试 1 次（Req: `requirements.md#req-5-1`，`requirements.md#req-5-2-2`；Impl: `apps/agent-api/src/anyagent_agent_api/app.py:458`；Module: `agent-api`）
- [x] P0 实现会话恢复：读取 `Session Store` 快照并按 `last_response_id/transcript` 组装首轮 OpenAI Responses `input`（Req: `requirements.md#req-4-6-1`，`requirements.md#req-3-1`；Impl: `apps/agent-api/src/anyagent_agent_api/app.py:239`, `apps/agent-api/src/anyagent_agent_api/app.py:452`；Module: `agent-api`）
- [x] P0 实现会话运行参数绑定：`model/temperature/top_p/frequency_penalty/presence_penalty/reasoning` 默认复用，仅显式传参时字段级 merge 更新（Req: `requirements.md#req-4-6-2`；Impl: `apps/agent-api/src/anyagent_agent_api/app.py:184`, `apps/agent-api/src/anyagent_agent_api/app.py:199`, `apps/agent-api/src/anyagent_agent_api/app.py:447`；Module: `agent-api`）
- [x] P0 修正工具回合参数继承：`previous_response_id` 后续回合必须复用同一 `effective_runtime_config`（Req: `requirements.md#req-4-6-2`；Impl: `apps/agent-api/src/anyagent_agent_api/app.py:1317`, `apps/agent-api/src/anyagent_agent_api/app.py:1606`, `apps/agent-api/src/anyagent_agent_api/app.py:1767`；Module: `agent-api`）
- [x] P1 在 run 终态回写会话快照（`resume_cursor + runtime_config`）并补结构化日志字段（Req: `requirements.md#req-4-6-1`，`requirements.md#req-4-6-2`，`requirements.md#req-7`；Impl: `apps/agent-api/src/anyagent_agent_api/app.py:572`, `apps/agent-api/src/anyagent_agent_api/app.py:614`, `apps/agent-api/src/anyagent_agent_api/app.py:454`；Module: `agent-api`）
- [x] P0 MCP：支持 Agent Pack 级 `mcp.json` 加载与启动期 fail-fast 校验（Req: `requirements.md#req-4-5`，`requirements.md#req-12-4`；Impl: `packages/anyagent/src/anyagent/agent_packs.py:164`；Module: `agent-api`）
- [x] P0 MCP：`/v1/responses` 合并 MCP tools 与 Tool Runtime manifest，并按 `mcp.` 前缀路由执行（Req: `requirements.md#req-4-5`，`requirements.md#req-5-2`；Impl: `apps/agent-api/src/anyagent_agent_api/app.py:984`；Module: `agent-api`）
  - refs: `apps/agent-api/src/anyagent_agent_api/app.py:1120`
  - refs: `packages/anyagent/src/anyagent/mcp/manager.py:16`
- [x] P1 收敛 Tool Runtime 客户端请求构造：manifest/execute 统一使用 shared typed model（Req: `requirements.md#req-4-5`，`requirements.md#req-5-1`，`requirements.md#req-5-2`；Impl: `apps/agent-api/src/anyagent_agent_api/clients/tool_runtime_client.py:1`；Module: `agent-api`）
- [x] P1 下沉 tool-loop 公共 helper 到 `packages/anyagent`：tool_choice 校验、function_call 提取、arguments 解析与 response_id 归一化统一复用（Req: `requirements.md#req-4-4`，`requirements.md#req-4-5`；Impl: `packages/anyagent/src/anyagent/protocol/openai_responses.py:46`；Module: `protocol/agent-api`）
  - refs: `packages/anyagent/src/anyagent/agent_runtime/tool_loop.py:139`
  - refs: `apps/agent-api/src/anyagent_agent_api/app.py:1012`
- [x] P1 下沉 session/runtime 与 Agent Pack 注入 helper：`app.py` 仅保留编排逻辑，通用纯函数移入 `agent_runtime/*`（Req: `requirements.md#req-4-6-1`，`requirements.md#req-4-6-2`，`requirements.md#req-2-1-1`；Impl: `packages/anyagent/src/anyagent/agent_runtime/session_runtime.py:1`；Module: `agent-runtime/agent-api`）
  - refs: `packages/anyagent/src/anyagent/agent_runtime/prompt_injection.py:1`
  - refs: `apps/agent-api/src/anyagent_agent_api/app.py:17`
- [x] P1 继续下沉 tool-loop payload helper：`allowed_tool_names` 提取与 follow-up body 构造统一复用，并收敛 `response.completed` 解码（Req: `requirements.md#req-4-4`，`requirements.md#req-4-5`；Impl: `packages/anyagent/src/anyagent/agent_runtime/tool_loop_payloads.py:1`；Module: `agent-runtime/protocol/agent-api`）
  - refs: `packages/anyagent/src/anyagent/protocol/openai_responses.py:105`
  - refs: `apps/agent-api/src/anyagent_agent_api/app.py:836`
- [x] P1 下沉工具结果组装 helper：tool runtime error 构造与 `function_call_output` 输出文本统一复用（Req: `requirements.md#req-4-5`，`requirements.md#req-5-1`；Impl: `packages/anyagent/src/anyagent/agent_runtime/tool_results.py:1`；Module: `agent-runtime/agent-api`）
  - refs: `apps/agent-api/src/anyagent_agent_api/app.py:1423`

## 决策 & 争议点

- [ ] Agent API 对外暴露哪些 “可选增强” endpoint（查询/取消）在 v0 是否实现（Req: `requirements.md#req-4-1`）
