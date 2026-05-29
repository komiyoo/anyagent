# Multi-Agent TODO

对应需求:`requirements.md#req-13`

## 目标

- Phase 1.8: Sub-Agent 最小可用版（`task()` tool 模式），让 AnyAgent 能处理复合任务
- Phase 4: parent / child / root run、quota、event replay 语义在 reference runtime 上可验收,作为后续多 runtime / 多 SDK 的兼容基线。

## 当前事实

- Runtime primitives:`packages/anyagent/src/anyagent/agent_runtime/`
- Stage Events:`anyagent.protocol.events`
- 长期文档:`docs/architecture/multi-agent/`
- 参考实现:DeerFlow SubagentExecutor（scheduler 线程池 + 独立 asyncio 事件循环,`task()` tool 模式）

## 里程碑

- M0: Sub-Agent 最小可用版（Phase 1.8）— in-process 子 Agent 委派,`task()` tool 注册,独立上下文
- M1: parent / child / root run 语义在 reference runtime 跑通
- M2: quota 与 event replay 在跨节点存储组合下一致
- M3: Multi-Agent contract test 套件成为新 runtime 接入门槛

## 任务

### Phase 1.8 — Sub-Agent 完整可用版

- [x] P0 设计 `task()` tool 的 schema（description, prompt, agent_id 参数）（Req: `requirements.md#req-13`; Impl: `packages/anyagent/src/anyagent/protocol/multi_agent.py:37`, `packages/anyagent/src/anyagent/agent_runtime/multiagent.py:110`, `tests/unit/agent_runtime/test_multiagent_task_schema.py:20`; Module: `anyagent.agent_runtime.multiagent`）
- [x] P0 实现 in-process SubAgentExecutor: 接收 task() 调用 → 创建子 Agent Loop → 独立上下文 → 返回结果（Req: `requirements.md#req-13`; Impl: `packages/anyagent/src/anyagent/agent_runtime/multiagent.py:604`, `packages/anyagent/src/anyagent/agent_runtime/tool_loop.py:350`, `tests/unit/agent_runtime/test_multiagent_task_schema.py:46`; Module: `anyagent.agent_runtime.multiagent`, `anyagent.agent_runtime.tool_loop`）
- [x] P0 子 Agent 并发限制:semaphore 控制并发（MAX_CONCURRENT_SUBAGENTS 默认 3,可通过 `agent.yaml` runtime.subagent.max_concurrent 配置）。参考 DeerFlow SubagentLimitMiddleware + Codex normalize_concurrency（Req: `requirements.md#req-13`; Impl: `packages/anyagent/src/anyagent/agent_runtime/multiagent.py:614`, `packages/anyagent/src/anyagent/agent_packs.py:77`, `tests/unit/agent_runtime/test_multiagent_task_schema.py:73`; Module: `anyagent.agent_runtime.multiagent`, `anyagent.agent_packs`）
- [x] P0 子 Agent 深度限制:depth 计数防递归嵌套（max_depth 默认 3）。子 Agent 的 task() tool 在 depth >= max_depth 时不注册。参考 Codex `exceeds_thread_spawn_depth_limit`（Req: `requirements.md#req-13`; Impl: `packages/anyagent/src/anyagent/agent_runtime/multiagent.py:659`, `tests/unit/agent_runtime/test_multiagent_task_schema.py:73`; Module: `anyagent.agent_runtime.multiagent`）
- [x] P0 子 Agent 超时机制:asyncio.wait_for 包装执行（默认 900s / 15min）。超时后发射 `subagent.timeout` Stage Event 并返回超时错误给父 Agent（Req: `requirements.md#req-13`; Impl: `packages/anyagent/src/anyagent/agent_runtime/multiagent.py:751`, `tests/unit/agent_runtime/test_multiagent_task_schema.py:105`; Module: `anyagent.agent_runtime.multiagent`）
- [x] P1 子 Agent Fork Mode:支持 `isolated`（独立上下文,当前默认）和 `fork_last_n(n)`（继承父上下文近 N 轮）两种模式。task() schema 新增可选 `context_mode` 参数。参考 Codex SpawnAgentForkMode（Req: `requirements.md#req-13`; Impl: `packages/anyagent/src/anyagent/protocol/multi_agent.py:43`, `packages/anyagent/src/anyagent/agent_runtime/multiagent.py:656`; Module: `anyagent.protocol.multi_agent`, `anyagent.agent_runtime.multiagent`）
- [x] P1 子 Agent Stage Events 追踪:Protocol 层新增 `AnyAgentSubAgentSpawnedEvent`（parent_run_id, child_run_id, agent_id, depth）和 `AnyAgentSubAgentCompletedEvent`（child_run_id, status, duration_ms）。SDK `events.stream_typed()` 支持 `include_subagent_events` 参数（Req: `requirements.md#req-13`; Impl: `packages/anyagent/src/anyagent/protocol/stage_events.py:315`, `packages/anyagent/src/anyagent/agent_runtime/multiagent.py:739`, `tests/fixtures/sdk_conformance/core_surface.json:852`; Module: `anyagent.protocol.stage_events`, `anyagent.agent_runtime.multiagent`, `sdk-conformance`）
- [x] P2 子 Agent 配置面:在 `agent.yaml` 新增 `runtime.subagent` 配置块（max_concurrent, max_depth, run_timeout_seconds, default_context_mode）（Req: `requirements.md#req-13`; Impl: `packages/anyagent/src/anyagent/agent_packs.py:77`, `packages/anyagent/src/anyagent/server/app.py:1330`; Module: `anyagent.agent_packs`, `anyagent.server.app`）

### Phase 4 — 完整 Multi-Agent Contract

- [ ] P1 整理 parent / child / root run 语义文档与 contract test 入口（Req: `requirements.md#req-13`、`requirements.md#req-13-1` ~ `requirements.md#req-13-8`）
- [ ] P1 quota 语义在跨节点 storage 下的一致性验收（Req: `requirements.md#req-13`）
- [ ] P2 Event replay 在 multi-agent 场景下的语义验收（与 storage replay 共用 contract）（Req: `requirements.md#req-13`、`requirements.md#req-3-1`）

## 决策 & 争议点

- [x] Sub-Agent 最小可用版优先级: 从 Phase 4 提升到 Phase 1.8（2026-05-29 决策: 内部使用场景复合任务是刚需）
- [x] Sub-Agent 并发/深度/超时参数: max_concurrent=3, max_depth=3, timeout=900s（2026-05-29 技术调研决策，参考 DeerFlow + Codex）
- [x] Fork Mode 设计: isolated（默认）+ fork_last_n 两种模式，通过 task() schema 可选参数控制（2026-05-29 技术调研决策，参考 Codex SpawnAgentForkMode）
- [ ] Multi-Agent 编排原语是否作为 protocol 一部分对外暴露,还是仅在 runtime 内部

## 参考

- `docs/architecture/overview/roadmap.md` Phase 1.8 / Phase 4
- `docs/architecture/multi-agent/`
- `docs/_notes/third-party/workspace-repos-tech-survey.md` — 技术调研报告
- DeerFlow SubagentExecutor: `deer-flow/backend/packages/harness/deerflow/subagents/executor.py`
- DeerFlow SubagentLimitMiddleware: `deer-flow/backend/packages/harness/deerflow/agents/middlewares/subagent_limit_middleware.py`
- Codex AgentRegistry: `codex/codex-rs/core/src/agent/registry.rs`
- Codex SpawnAgentForkMode: `codex/codex-rs/core/src/agent/control.rs`
