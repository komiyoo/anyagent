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

### Phase 1.8 — Sub-Agent 最小可用版

- [x] P0 设计 `task()` tool 的 schema（description, prompt, agent_id 参数）（Req: `requirements.md#req-13`; Impl: `packages/anyagent/src/anyagent/protocol/multi_agent.py:37`, `packages/anyagent/src/anyagent/agent_runtime/multiagent.py:110`, `tests/unit/agent_runtime/test_multiagent_task_schema.py:20`; Module: `anyagent.agent_runtime.multiagent`）
- [ ] P0 实现 in-process SubAgentExecutor: 接收 task() 调用 → 创建子 Agent Loop → 独立上下文 → 返回结果（Req: `requirements.md#req-13`）
- [ ] P1 子 Agent 的 Stage Events 追踪（parent_run_id 关联）（Req: `requirements.md#req-13`）
- [ ] P1 子 Agent 并发限制（MAX_CONCURRENT_SUBAGENTS 配置）（Req: `requirements.md#req-13`）
- [ ] P2 子 Agent 超时机制（Req: `requirements.md#req-13`）

### Phase 4 — 完整 Multi-Agent Contract

- [ ] P1 整理 parent / child / root run 语义文档与 contract test 入口（Req: `requirements.md#req-13`、`requirements.md#req-13-1` ~ `requirements.md#req-13-8`）
- [ ] P1 quota 语义在跨节点 storage 下的一致性验收（Req: `requirements.md#req-13`）
- [ ] P2 Event replay 在 multi-agent 场景下的语义验收（与 storage replay 共用 contract）（Req: `requirements.md#req-13`、`requirements.md#req-3-1`）

## 决策 & 争议点

- [ ] Multi-Agent 编排原语是否作为 protocol 一部分对外暴露,还是仅在 runtime 内部
- [x] Sub-Agent 最小可用版优先级: 从 Phase 4 提升到 Phase 1.8（2026-05-29 决策: 内部使用场景复合任务是刚需）

## 参考

- `docs/architecture/overview/roadmap.md` Phase 1.8 / Phase 4
- `docs/architecture/multi-agent/`
- DeerFlow SubagentExecutor: `deer-flow/backend/packages/harness/deerflow/subagents/executor.py`
