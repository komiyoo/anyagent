# Server Runtime TODO

对应需求:`requirements.md#req-5`、`requirements.md#req-4-3`、`requirements.md#req-4-7`

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

### Phase 1 — Responses API Provider Hardening

- [x] P1 统一 Anthropic/Gemini provider 翻译宿主（后续已删除，Responses 改 pydantic-ai）（Req: `requirements.md#req-4-5`; Impl: `packages/anyagent/src/anyagent/agent_runtime/loop/models.py`; Module: `anyagent.agent_runtime.loop.models`）
- [x] P1 Chatwoot 已分配真人坐席时跳过 bot 回复：webhook 快照 + 发信前 live GET，不把 `status=open` 当 handoff 信号（Req: `requirements.md#req-6`; Impl: `packages/anyagent/src/anyagent/plugins/builtin/chatwoot_connector/chatwoot.py`, `packages/anyagent/src/anyagent/plugins/builtin/chatwoot_connector/plugin.py`; Module: `anyagent.plugins.builtin.chatwoot_connector`）
- [x] P1 Chatwoot bot 回复后保持 open：不限 pending，resolved/snoozed/缺 status 也打开；从不 resolve/snooze（Req: `requirements.md#req-6`; Impl: `packages/anyagent/src/anyagent/plugins/builtin/chatwoot_connector/plugin.py`; Module: `anyagent.plugins.builtin.chatwoot_connector`）

## 参考

- `docs/architecture/overview/roadmap.md` Phase 2 / Phase 4
- `docs/architecture/runtime/stateless-agent-service-architecture.md`
- `docs/architecture/runtime/agent-server-runtime-entities.md`
- `docs/architecture/control-plane/studio-control-plane-and-observability.md`
- `docs/_notes/third-party/workspace-repos-tech-survey.md` — 技术调研报告
- DeerFlow LoopDetectionMiddleware: `deer-flow/backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py`
- DeerFlow SummarizationMiddleware: `deer-flow/backend/packages/harness/deerflow/agents/middlewares/summarization_middleware.py`
- Codex compact prompt: `codex/codex-rs/core/templates/compact/prompt.md`
- Pi-mono compaction: `pi-mono/packages/agent/src/harness/compaction/compaction.ts`
- DeerFlow config hot-reload: `deer-flow/backend/packages/harness/deerflow/config/app_config.py`
