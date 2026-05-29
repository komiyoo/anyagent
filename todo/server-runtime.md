# Server Runtime TODO

对应需求:`requirements.md#req-5`、`requirements.md#req-4-3`

## 目标

- 让 Python reference server 在单机主路径稳定的基础上,具备多节点 / 多 workspace 的运行能力,并保持 contract 可替换。

## 当前事实

- Server 入口:`packages/anyagent/src/anyagent/server/app.py`
- Agent loop:`packages/anyagent/src/anyagent/agent_runtime/`
- Gateway / session 路由:`packages/anyagent/src/anyagent/gateway/`
- Session / Run / Event 抽象:`anyagent.protocol.*` + `anyagent.storage`
- 长期架构:`docs/architecture/runtime/stateless-agent-service-architecture.md`

## 里程碑

- M1:系统性持久化 — Prompt Context / Tool Execution / Model Request Replay（Phase 1.5）
- M2:跨节点 Run 调度 & lock contract 实装（Phase 2）
- M3:Unified Observability Sink — 统一 envelope 出口 + 外部审计对接（Phase 2）
- M4:第二 server runtime（异语言）通过 reference conformance suite（Phase 4）

## 任务

### Phase 1.5 — Agentic Ecosystem Hardening

- [x] P0 Skill → Agent Loop 注入管道:在 `agent_runtime` 增加 `SkillInjector`,负责解析用户输入中的 skill mention → 读取 SKILL.md → 注入到 prompt context,带可配置 token budget(Req: `requirements.md#req-5`; Impl: `packages/anyagent/src/anyagent/agent_runtime/skill_injector.py:40`; Module: `anyagent.agent_runtime`)
- [ ] P1 配置层级 merge:支持 system(`/etc/anyagent/`) → user(`~/.anyagent/`) → workspace(`.anyagent/`) → session(CLI override) 的配置合并策略,workspace 层有安全 denylist(Req: `requirements.md#req-5`)
- [ ] P1 Config 热重载（Phase 1.5 部分）:agent.yaml / mcp.json mtime 检测,热重载字段（model、tools、skills）即时生效,冷重启字段（storage、sandbox）需重启。参考 DeerFlow mtime 轮询模式（Req: `requirements.md#req-5`）
- [ ] P1 MCP 生命周期 Stage Events:对齐 `anyagent.protocol.events` 发射 `mcp.server.starting` / `mcp.server.ready` / `mcp.server.failed` 事件,可被 SDK 消费(Req: `requirements.md#req-5`、`requirements.md#req-5-13`)
- [ ] P2 AGENTS.md 层级遍历:支持从 cwd 到 project root 每层收集 AGENTS.md,拼接后注入 agent instructions,带 byte budget 限制(monorepo 场景)(Req: `requirements.md#req-5`)

### Phase 1.8 — Internal Productivity（内部生产力提升）

- [x] P0 Agent Loop Middleware 接口:在 `agent_runtime/` 新增 `middleware.py`,定义 4-hook Protocol（`before_model_call`、`after_model_call`、`before_tool_execute`、`after_tool_execute`）+ `MiddlewareContext` 数据类 + `MiddlewareChain` 顺序执行器。`agent.yaml` 的 `runtime.middlewares` 声明加载顺序（Req: `requirements.md#req-5`; Impl: `packages/anyagent/src/anyagent/agent_runtime/middleware.py:17`, `packages/anyagent/src/anyagent/agent_runtime/tool_loop.py:42`, `tests/unit/agent_runtime/test_middleware_chain.py:16`; Module: `anyagent.agent_runtime.middleware`, `anyagent.agent_runtime.tool_loop`）
- [x] P0 上下文压缩（内置 middleware）:实现 `ContextCompactionMiddleware`。触发策略:在 `before_model_call` 中检测 token 使用率 > 阈值（默认 0.8）。压缩算法:Codex handoff prompt 模板（progress + decisions + next steps）+ Pi-mono cut-point 选择（不在 tool_planned → tool_result 之间切断）+ 迭代式摘要更新（新摘要作为 UPDATE 生成）。配置:阈值、keep_recent_tokens(20000)、strategy。发射 `context.compacted` Stage Event（Req: `requirements.md#req-5`; Impl: `packages/anyagent/src/anyagent/agent_runtime/middlewares/context_compaction.py:12`, `packages/anyagent/src/anyagent/protocol/stage_events.py:344`, `tests/unit/agent_runtime/test_context_compaction.py:9`; Module: `anyagent.agent_runtime.middlewares.context_compaction`, `anyagent.protocol.stage_events`）
- [x] P0 循环检测（内置 middleware）:实现 `LoopDetectionMiddleware`。在 `after_model_call` 中 hash tool_calls（name + stable_tool_key）→ 滑动窗口(20) → warn_threshold(3) 注入警告 → hard_limit(5) strip tool_calls 强制文本输出。`_stable_tool_key` 对 read_file 按行号 bucket(200)、write_file 全 args hash、其他工具取 salient fields。发射 `agent.loop_warning` / `agent.loop_terminated` Stage Event。默认开启（Req: `requirements.md#req-5`; Impl: `packages/anyagent/src/anyagent/agent_runtime/middlewares/loop_detection.py:16`, `packages/anyagent/src/anyagent/server/app.py:125`, `tests/unit/agent_runtime/test_loop_detection.py:11`; Module: `anyagent.agent_runtime.middlewares.loop_detection`, `anyagent.server.app`）
- [ ] P1 Config 热重载:每次请求 stat `agent.yaml` / `mcp.json` mtime,变化则重新加载。明确区分热重载字段（model、tools、skills、middlewares）vs 冷重启字段（storage、sandbox backend）。参考 DeerFlow `app_config.py` mtime 轮询模式（Req: `requirements.md#req-5`）
- [ ] P2 嵌入 DeerFlow Skills:适配 `deep-research` skill（MIT License）到 `.anyagent/skills/` 格式,验证 Skill → Agent Loop 注入兼容性（Req: `requirements.md#req-5`）
- [ ] P2 开发者体验优化:`anyagent dev` 热重载、日志可读性、Studio 调试能力提升（Req: `requirements.md#req-5`）

### Phase 1.5 — 系统性持久化（Systematic Persistence）

> 详细任务清单见 `todo/persistence.md`

- [x] P0 Prompt Context Replay：rendered fragments 持久化 + 历史查询 API（Req: `requirements.md#req-5-13`；Detail: `todo/persistence.md` M1；Impl: `packages/anyagent/src/anyagent/protocol/stage_events.py:258`, `packages/anyagent/src/anyagent/server/app.py:798`, `packages/anyagent/src/anyagent/server/response_persistence.py:100`；Module: `anyagent.protocol.stage_events`, `anyagent.server.app`, `anyagent.server.response_persistence`）
- [x] P1 Tool Execution Replay：tool input/output full payload 持久化 + 查询（Req: `requirements.md#req-5-13`；Detail: `todo/persistence.md` M2；Impl: `packages/anyagent/src/anyagent/protocol/stage_events.py:246`, `packages/anyagent/src/anyagent/agent_runtime/tool_loop.py:263`, `packages/anyagent/src/anyagent/server/app.py:842`；Module: `anyagent.protocol.stage_events`, `anyagent.agent_runtime.tool_loop`, `anyagent.server.app`）
- [x] P1 Model Request Replay：applied_body 持久化 + replay API（Req: `requirements.md#req-5-13`；Detail: `todo/persistence.md` M3；Impl: `packages/anyagent/src/anyagent/protocol/stage_events.py:260`, `packages/anyagent/src/anyagent/server/app.py:1293`, `packages/anyagent/src/anyagent/server/app.py:1484`；Module: `anyagent.protocol.stage_events`, `anyagent.server.app`）

### Phase 2 — Production Runtime Hardening

- [x] P0 设计跨节点 Run 调度与 lock contract,落 ADR(Req: `requirements.md#req-5`; Impl: `docs/architecture/decisions/run-scheduling-lock-contract.md:10`; Module: `docs.architecture.decisions`)
- [x] P0 实装 lock contract 的 Redis 与 PostgreSQL adapter,跑通跨节点 resume / cancel(Req: `requirements.md#req-5`、`requirements.md#req-3-1`; Impl: `packages/anyagent/src/anyagent/storage/external/postgres.py:20`, `packages/anyagent/src/anyagent/storage/external/sqlalchemy_backend.py:403`, `tests/unit/server/test_lease_lock_contract.py:45`, `tests/unit/server/test_optional_responses.py:102`; Module: `anyagent.storage`)
- [ ] P1 Unified Observability Sink：统一 envelope 出口 + 外部审计系统对接（Req: `requirements.md#req-5-13`；Detail: `todo/persistence.md` M4）
- [ ] P2 整理 reference conformance suite,为第二 server runtime 接入准备验收基线(Req: `requirements.md#req-5`、`requirements.md#req-7`)

## 决策 & 争议点

- [x] 上下文压缩算法选型:Codex handoff prompt + Pi-mono cut-point + 迭代式摘要（2026-05-29 技术调研决策）
- [x] 循环检测算法选型:DeerFlow hash + 滑动窗口 + 双阈值 + stable_tool_key（2026-05-29 技术调研决策）
- [x] 框架扩展模型:4-hook Middleware 接口（精简版,非 DeerFlow 18 middleware 全量）（2026-05-29 技术调研决策）
- [x] Config 热重载机制:mtime 轮询（参考 DeerFlow），区分热/冷字段（2026-05-29 技术调研决策）
- [ ] 跨节点 lock 的底座选择:Redis-only vs storage-agnostic vs 二者皆支持
- [ ] Observability envelope:OTel 直接对接 vs 仓内中间层 + 多 sink 适配

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
