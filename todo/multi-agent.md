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

## 当前状态

- Phase 1.8 Sub-Agent（`task()` tool 模式）任务已全部完成;已完成条目已清理,历史记录请查看 Git。
- 已实现能力的长期口径见架构文档:
  - `task()` tool schema、in-process SubAgentExecutor、并发/深度/超时限制、Fork Mode、Sub-Agent Stage Events 与 parent/child/root run 语义、contract test 入口:`docs/architecture/multi-agent/multi-agent-collaboration.md`

## 待处理

### Phase 4 — 完整 Multi-Agent Contract

- [x] P1 quota 语义在跨节点 storage 下的一致性验收（Req: `requirements.md#req-13`；Module: `agent-runtime`；Impl: `packages/anyagent/src/anyagent/agent_runtime/multiagent_quota.py:42`、`tests/contract/test_multiagent_contract.py:13`）
- [x] P2 Event replay 在 multi-agent 场景下的语义验收（与 storage replay 共用 contract）（Req: `requirements.md#req-13`、`requirements.md#req-3-1`；Module: `storage`；Impl: `tests/contract/test_multiagent_contract.py:39`、`packages/anyagent/src/anyagent/storage/replay.py:71`）

## 决策 & 争议点

- [x] Multi-Agent 编排原语是否作为 protocol 一部分对外暴露,还是仅在 runtime 内部：当前保持 runtime/internal contract，不新增 public protocol；对外稳定面仍是 Stage Events + replay contract。（Module: `agent-runtime`；Impl: `docs/architecture/multi-agent/multi-agent-collaboration.md:158`）

## 参考

- `docs/architecture/overview/roadmap.md` Phase 1.8 / Phase 4
- `docs/architecture/multi-agent/`
- `docs/_notes/third-party/workspace-repos-tech-survey.md` — 技术调研报告
- DeerFlow SubagentExecutor: `deer-flow/backend/packages/harness/deerflow/subagents/executor.py`
- DeerFlow SubagentLimitMiddleware: `deer-flow/backend/packages/harness/deerflow/agents/middlewares/subagent_limit_middleware.py`
- Codex AgentRegistry: `codex/codex-rs/core/src/agent/registry.rs`
- Codex SpawnAgentForkMode: `codex/codex-rs/core/src/agent/control.rs`
