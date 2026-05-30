# Server Runtime TODO

对应需求:`requirements.md#req-5`、`requirements.md#req-4-3`

## 目标

- 让 Python reference server 在单机主路径稳定的基础上,具备多节点 / 多 workspace 的运行能力,并保持 contract 可替换。

## 当前状态

- Phase 1.5 / 1.8 / Phase 2 的已完成条目已清理;历史记录请查看 Git。下方仅保留未完成项。
- 已实现能力的长期口径见架构文档:
  - 配置层级 merge / 热重载 / MCP 生命周期:`docs/architecture/runtime/agent-packs-and-runtime-config.md`
  - Agent Loop Middleware / 上下文压缩 / 循环检测:`docs/architecture/runtime/agent-loop-middleware.md`
  - 跨节点 Run 调度 & lock contract:`docs/architecture/runtime/stateless-agent-service-architecture.md`、`docs/architecture/decisions/run-scheduling-lock-contract.md`
  - Model Provider translator / capability / registry:`docs/architecture/api/model-provider-translators.md`

## 当前事实

- Server 入口:`packages/anyagent/src/anyagent/server/app.py`
- Agent loop:`packages/anyagent/src/anyagent/agent_runtime/`
- Gateway / session 路由:`packages/anyagent/src/anyagent/gateway/`
- Session / Run / Event 抽象:`anyagent.protocol.*` + `anyagent.storage`
- 长期架构:`docs/architecture/runtime/stateless-agent-service-architecture.md`

## 里程碑

- M1:系统性持久化 — Prompt Context / Tool Execution / Model Request Replay（Phase 1.5）✅
- M2:跨节点 Run 调度 & lock contract 实装（Phase 2）✅
- M3:Unified Observability Sink — 统一 envelope 出口 + 外部审计对接（Phase 2）✅
- M4:第二 server runtime（异语言）通过 reference conformance suite（Phase 4）

## 任务

### Phase 1 — Responses API Provider Hardening

- [x] P1 统一 Anthropic/Gemini provider 翻译宿主,补齐 Gemini function calling、Anthropic `tool_choice=required` 与 developer/system prompt 映射,并收敛 provider registry（Req: `requirements.md#req-4-5`; Impl: `packages/anyagent/src/anyagent/agent_runtime/model_providers/_translating_provider.py`; Module: `anyagent.agent_runtime.model_providers`）

### Phase 1.5 — Agentic Ecosystem Hardening

- [ ] P2 AGENTS.md 层级遍历:支持从 cwd 到 project root 每层收集 AGENTS.md,拼接后注入 agent instructions,带 byte budget 限制(monorepo 场景)(Req: `requirements.md#req-5`)

### Phase 1.8 — Internal Productivity（内部生产力提升）

- [ ] P2 嵌入 DeerFlow Skills:适配 `deep-research` skill（MIT License）到 `.anyagent/skills/` 格式,验证 Skill → Agent Loop 注入兼容性（Req: `requirements.md#req-5`）
- [ ] P2 开发者体验优化:`anyagent dev` 热重载、日志可读性、Studio 调试能力提升（Req: `requirements.md#req-5`）

## 决策 & 争议点

- [ ] 跨节点 lock 的底座选择:Redis-only vs storage-agnostic vs 二者皆支持

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
