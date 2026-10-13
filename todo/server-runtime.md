# Server Runtime TODO

对应需求:`requirements.md#req-5`、`requirements.md#req-4-3`、`requirements.md#req-4-7`、`requirements.md#req-0-2`

## 目标

- 让 Python reference server 在单机主路径稳定的基础上,具备多节点 / 多 workspace 的运行能力,并保持 contract 可替换。

## 当前状态

- Phase 1.5 / 1.8 / Phase 2 的已完成条目已清理;历史记录请查看 Git。下方仅保留未完成项。
- 已实现能力的长期口径见架构文档:
  - 配置层级 merge / 热重载 / MCP 生命周期:`docs/architecture/runtime/agent-packs-and-runtime-config.md`
  - Agent loop（pydantic-ai）/ 模型映射 / OTLP:`docs/architecture/runtime/agent-loop.md`
  - 跨节点 Run 调度 & lock contract:`docs/architecture/runtime/stateless-agent-service-architecture.md`、`docs/architecture/decisions/run-scheduling-lock-contract.md`
  - 历史 4-hook / translator:`docs/architecture/runtime/agent-loop-middleware.md`、`docs/architecture/api/model-provider-translators.md`

## 当前任务（pydantic-ai loop + Langfuse）

口径：[docs/architecture/decisions/pydantic-ai-loop-and-langfuse.md](../docs/architecture/decisions/pydantic-ai-loop-and-langfuse.md)。执行顺序见 `docs/plans/` 下对应计划，不要在本文件复制步骤。

- [x] P1 用 pydantic-ai 适配器实现 `run_tool_loop_*`，保持 Responses / Gateway 调用面（Req: `requirements.md#req-4-7`; Impl: `packages/anyagent/src/anyagent/agent_runtime/loop/run.py`, `packages/anyagent/src/anyagent/agent_runtime/tool_loop.py`; Module: `anyagent.agent_runtime.loop`）
- [x] P1 将 `AGENTS.md` / context providers / skill catalog 经 prompt envelope 注入 pydantic-ai instructions（Req: `requirements.md#req-4-7`、`requirements.md#req-2-1`; Impl: `packages/anyagent/src/anyagent/agent_runtime/loop/models.py`; Module: `anyagent.agent_runtime.loop.models`）
- [x] P1 Tool Runtime manifest/execute 包装为 pydantic-ai tools，不平行第二套 handler（Req: `requirements.md#req-4-5`; Impl: `packages/anyagent/src/anyagent/agent_runtime/loop/tools.py`; Module: `anyagent.agent_runtime.loop.tools`）
- [x] P1 OTLP 导出到 Langfuse；未配置则关闭跟踪且服务可跑（Req: `requirements.md#req-5-13`、`requirements.md#req-4-7`; Impl: `packages/anyagent/src/anyagent/agent_runtime/loop/otel.py`; Module: `anyagent.agent_runtime.loop.otel`）
- [x] P2 主路径验收通过后删除自研 translator 热路径，middleware 映射为 capabilities（Req: `requirements.md#req-4-7`; Impl: `packages/anyagent/src/anyagent/server/routes/responses.py`, `packages/anyagent/src/anyagent/agent_runtime/loop/hooks.py`; Module: `anyagent.agent_runtime.loop.hooks`）

## 当前任务（scripted reply 扩展点与 connector 回复节奏）

执行计划：`docs/plans/2026/09-07/scripted-reply-扩展点与-connector-回复节奏-614d.md`。

- [x] P1 `ScriptedReply` 协议模型 + `anyagent.response.scripted` stage event + `ScriptedReplyRequest` / `ScriptedReplyProvider` 契约与 classpath 装载（Req: `requirements.md#req-4-6-1`; Impl: `packages/anyagent/src/anyagent/protocol/scripted_reply.py`, `packages/anyagent/src/anyagent/protocol/stage_events.py`, `packages/anyagent/src/anyagent/agent_runtime/scripted_reply.py`, `packages/anyagent/src/anyagent/agent_runtime/classpath.py`; Module: `anyagent.protocol.scripted_reply`, `anyagent.agent_runtime.scripted_reply`）
- [x] P1 `RuntimeSpec.scripted_reply_providers` + 内置 runtime worker 内（session lease 下、loop 前）命中判定；命中合成 Response 走既有 finalize / SSE persist 路径，进入 `fallback_transcript_items`；异常/超时/装载失败降级继续 loop（Req: `requirements.md#req-4-6-1`; Impl: `packages/anyagent/src/anyagent/config/agents.py`, `packages/anyagent/src/anyagent/server/handlers/scripted_reply.py`, `packages/anyagent/src/anyagent/server/routes/responses.py`, `packages/anyagent/src/anyagent/agent_runtime/loop/run.py`; Module: `anyagent.server.routes.responses`; Test: `tests/unit/agent_runtime/test_scripted_reply.py`, `tests/integration/server/test_scripted_reply_responses.py`）
- [x] P1 Connector 回复节奏下限与 typing indicator：`ConnectorOutboundDelivery.set_typing` 可选能力、Chatwoot `toggle_typing_status` 实现、`CHATWOOT_REPLY_PACING_*` floor 在二次人工接管检查之前补足，默认关闭（Req: `requirements.md#req-6-1`; Impl: `packages/anyagent/src/anyagent/gateway/connector_contracts.py`, `packages/anyagent/src/anyagent/plugins/builtin/chatwoot_connector/chatwoot.py`, `packages/anyagent/src/anyagent/plugins/builtin/chatwoot_connector/plugin.py`; Module: `anyagent.plugins.builtin.chatwoot_connector`; Test: `tests/unit/gateway/test_chatwoot_reply_pacing.py`, `tests/integration/server/test_chatwoot_connector_flow.py`）
- [ ] P2 分布式 runtime（`routes/distributed_responses.py` / `responses/response_execution.py`）支持 scripted reply（Req: `requirements.md#req-4-6-1`; 当前文档标注不支持）
- [x] P1 scripted reply 可选 `content_type` / `content_attributes` 经 Response message item 与 Chatwoot connector 透传；插件调用 `_process_incoming_message` 时可标记 `input_source`（Req: `requirements.md#req-4-6-1`、`requirements.md#req-6`; Impl: `packages/anyagent/src/anyagent/protocol/scripted_reply.py`, `packages/anyagent/src/anyagent/agent_runtime/loop/run.py`, `packages/anyagent/src/anyagent/server/routes/responses.py`, `packages/anyagent/src/anyagent/plugins/builtin/chatwoot_connector/plugin.py`, `packages/anyagent/src/anyagent/plugins/builtin/chatwoot_connector/chatwoot.py`; Module: `anyagent.protocol.scripted_reply`, `anyagent.plugins.builtin.chatwoot_connector`; Test: `tests/unit/agent_runtime/test_scripted_reply.py`, `tests/integration/server/test_scripted_reply_responses.py`, `tests/unit/gateway/test_chatwoot_reply_pacing.py`）

## 当前事实

- Server 入口:`packages/anyagent/src/anyagent/server/app.py`
- Agent loop:`packages/anyagent/src/anyagent/agent_runtime/loop/`（合同 `tool_loop.py`；口径 `docs/architecture/runtime/agent-loop.md`）
- Gateway / session 路由:`packages/anyagent/src/anyagent/gateway/`
- Session / Run / Event 抽象:`anyagent.protocol.*` + `anyagent.storage`
- 长期架构:`docs/architecture/runtime/stateless-agent-service-architecture.md`

## 里程碑

- M1:系统性持久化 — Prompt Context / Tool Execution / Model Request Replay（Phase 1.5）✅
- M2:跨节点 Run 调度 & lock contract 实装（Phase 2）✅
- M3:Unified Observability Sink — 统一 envelope 出口 + 外部审计对接（Phase 2）✅
- M4:第二 server runtime（异语言）通过 reference conformance suite（Phase 4）
- M5:pydantic-ai loop + Langfuse OTLP（Req: `requirements.md#req-4-7`）✅

## 已完成任务

- [x] P1 受信任 middleware classpath 支持原生 pydantic-ai capability，模型输出校验覆盖非流式与 SSE，保留旧工具回调（Req: `requirements.md#req-4-7`; Impl: `packages/anyagent/src/anyagent/agent_runtime/middleware.py:112`, `packages/anyagent/src/anyagent/agent_runtime/loop/hooks.py:31`; Module: `anyagent.agent_runtime.middleware`, `anyagent.agent_runtime.loop.hooks`; Test: `tests/unit/agent_runtime/test_pydantic_ai_loop.py`）
- [x] P1 Chatwoot 事件与 Responses 请求保留消息关联键，区分访客、Bot 和模板消息（Req: `requirements.md#req-6`; Impl: `packages/anyagent/src/anyagent/plugins/builtin/chatwoot_connector/chatwoot.py:564`, `packages/anyagent/src/anyagent/server/routes/responses.py:312`; Module: `anyagent.plugins.builtin.chatwoot_connector`, `anyagent.server.routes.responses`; Test: `tests/unit/gateway/test_connector_contracts.py`, `tests/integration/server/test_chatwoot_connector_flow.py`, `tests/integration/server/test_scripted_reply_responses.py`）
- [x] P1 Chatwoot quick prompt 字段透传：请求 metadata 与平台事件保留 `lt_quick_prompt_id` / `quick_prompt_id`，复用既有来源合并与字符串校验（Req: `requirements.md#req-6`; Impl: `packages/anyagent/src/anyagent/plugins/builtin/chatwoot_connector/chatwoot.py:470`; Module: `anyagent.plugins.builtin.chatwoot_connector`; Test: `tests/unit/gateway/test_connector_contracts.py`, `tests/integration/server/test_chatwoot_connector_flow.py`）

### Phase 1 — Responses API Provider Hardening

- [x] P1 统一 Anthropic/Gemini provider 翻译宿主（后续已删除，Responses 改 pydantic-ai）（Req: `requirements.md#req-4-5`; Impl: `packages/anyagent/src/anyagent/agent_runtime/loop/models.py`; Module: `anyagent.agent_runtime.loop.models`）
- [x] P1 Chatwoot 已分配真人坐席时跳过 bot 回复：webhook 快照 + 发信前 live GET，不把 `status=open` 当 handoff 信号（Req: `requirements.md#req-6`; Impl: `packages/anyagent/src/anyagent/plugins/builtin/chatwoot_connector/chatwoot.py`, `packages/anyagent/src/anyagent/plugins/builtin/chatwoot_connector/plugin.py`; Module: `anyagent.plugins.builtin.chatwoot_connector`）
- [x] P1 Chatwoot bot 回复后保持 open：不限 pending，resolved/snoozed/缺 status 也打开；从不 resolve/snooze（Req: `requirements.md#req-6`; Impl: `packages/anyagent/src/anyagent/plugins/builtin/chatwoot_connector/plugin.py`; Module: `anyagent.plugins.builtin.chatwoot_connector`）

## 已完成任务（0.5 单一配置文件与 CLI）

口径：`docs/architecture/decisions/single-workspace-config.md`。

- [x] 工作区配置收成 `.anyagent/anyagent.yaml`。`load_effective_config` 按 system、user、workspace、CLI 合并，并用 `${VAR}` 插值。（Req: `requirements.md#req-0-2`；Impl: `packages/anyagent/src/anyagent/config/loader.py:129`、`packages/anyagent/src/anyagent/config/schema.py:227`、`packages/anyagent/src/anyagent/config/env.py:84`、`packages/anyagent/src/anyagent/config/defaults.py:13`、`packages/anyagent/src/anyagent/config/merge.py:10`；Module: `anyagent.config`）
- [x] `.env` 与 `.env.local` 只由 `load_dotenv` 读一次，不覆盖进程里已有的变量。（Req: `requirements.md#req-0-2`；Impl: `packages/anyagent/src/anyagent/config/env.py:57`；Module: `anyagent.config.env`）
- [x] 没有 agent 目录时使用内置 `main`。agent 目录可以只有 `AGENTS.md`，`agent.yaml` 可选。（Req: `requirements.md#req-0-2`、`requirements.md#req-2-1`；Impl: `packages/anyagent/src/anyagent/config/agents.py:271`、`packages/anyagent/src/anyagent/config/agents.py:337`；Module: `anyagent.config.agents`）
- [x] CLI 拆成 `anyagent.cli`。`serve` 与 `dev` 共用参数。`storage` 与 `db` 是子命令。（Req: `requirements.md#req-0-2`；Impl: `packages/anyagent/src/anyagent/cli/main.py:33`、`packages/anyagent/src/anyagent/cli/serve.py:87`、`packages/anyagent/src/anyagent/cli/storage.py:18`；Module: `anyagent.cli`）
- [x] `anyagent init` 与 `anyagent add agent|skill|tool|mcp|plugin` 生成工作区骨架，并写出 JSON Schema。（Req: `requirements.md#req-0-2`；Impl: `packages/anyagent/src/anyagent/scaffold/init_workspace.py:45`、`packages/anyagent/src/anyagent/scaffold/add_component.py:34`、`packages/anyagent/src/anyagent/scaffold/schema_export.py:21`、`packages/anyagent/src/anyagent/cli/workspace.py:38`；Module: `anyagent.scaffold`）
- [x] `config show` 打印脱敏后的生效配置。`--sources` 给出层和插值用到的环境变量。`credentials.runtime_env` 显示环境变量名和 `credential:<id>`。（Req: `requirements.md#req-0-2`；Impl: `packages/anyagent/src/anyagent/cli/workspace.py:155`；Module: `anyagent.cli.workspace`）
- [x] `anyagent dev` 在 API key 为空时填入 `anyagent-dev-key`。`anyagent serve` 在 host 不是 loopback 且 API key 为空时拒绝启动。（Req: `requirements.md#req-0-2`；Impl: `packages/anyagent/src/anyagent/cli/serve.py:154`、`packages/anyagent/src/anyagent/cli/serve.py:181`；Module: `anyagent.cli.serve`）
- [x] 暂时只提供源码安装：GitHub Actions 去掉 `publish-packages`，安装文档改为 `git+https` 加 `subdirectory=packages/anyagent`，发版即版本号加 `vX.Y.Z` tag。（Req: `requirements.md#req-9`；Impl: `.github/workflows/ci.yml:1`、`docs/release-checklist.md:1`、`docs/guides/deployment.md:18`；Module: CI / release）

## 参考

- `docs/architecture/overview/roadmap.md` Phase 2 / Phase 4
- `docs/architecture/decisions/single-workspace-config.md`
- `docs/architecture/runtime/stateless-agent-service-architecture.md`
- `docs/architecture/runtime/agent-server-runtime-entities.md`
- `docs/architecture/control-plane/studio-control-plane-and-observability.md`
- `docs/_notes/third-party/workspace-repos-tech-survey.md` — 技术调研报告
- DeerFlow LoopDetectionMiddleware: `deer-flow/backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py`
- DeerFlow SummarizationMiddleware: `deer-flow/backend/packages/harness/deerflow/agents/middlewares/summarization_middleware.py`
- Codex compact prompt: `codex/codex-rs/core/templates/compact/prompt.md`
- Pi-mono compaction: `pi-mono/packages/agent/src/harness/compaction/compaction.ts`
- DeerFlow config hot-reload: `deer-flow/backend/packages/harness/deerflow/config/app_config.py`
