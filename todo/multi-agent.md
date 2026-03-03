# Multi-Agent TODO

对应需求：`requirements.md#req-13`

## 目标

- 提供 Codex 风格的 multi-agent 编排原语（spawn/send/wait/close/resume），并具备治理与隔离策略。

## 里程碑（Milestones）

- M1：系统工具契约与最小实现可用（本地/单实例）
- M2：治理（限制/审计/可观测）到位
- M3：与 `/v1/responses` streaming 事件对齐

## 任务（Tasks）

- [x] P0 明确 multi-agent v0 目标/非目标与限制项（Req: `requirements.md#req-13-1`，`requirements.md#req-13-4`；Impl: `docs/_dev/multi-agent/multi-agent-v0.md:1`；Module: `multi-agent`）
- [x] P0 定义 child thread/session 的核心实体与存储结构（Req: `requirements.md#req-13-2`；Impl: `docs/_dev/multi-agent/multi-agent-entities.md:1`；Module: `multi-agent`）
- [x] P0 落地系统工具：`spawn_agent`（Req: `requirements.md#req-13-3`；Impl: `apps/agent-api/src/anyagent_agent_api/multiagent/manager.py:1`；Module: `multi-agent`）
- [x] P0 落地系统工具：`send_input`（Req: `requirements.md#req-13-3`；Impl: `apps/agent-api/src/anyagent_agent_api/multiagent/manager.py:252`；Module: `multi-agent`）
- [x] P0 落地系统工具：`wait`（Req: `requirements.md#req-13-3`；Impl: `apps/agent-api/src/anyagent_agent_api/multiagent/manager.py:328`；Module: `multi-agent`）
- [x] P1 落地系统工具：`close_agent` / `resume_agent`（Req: `requirements.md#req-13-3`，`requirements.md#req-13-8`；Impl: `apps/agent-api/src/anyagent_agent_api/multiagent/manager.py:449`；Module: `multi-agent`）
- [x] P1 落地子 agent 与 tool/skills 的隔离策略（Req: `requirements.md#req-13-5`；Impl: `apps/agent-api/src/anyagent_agent_api/multiagent/manager.py:297`；Module: `multi-agent`）
- [x] P2 落地事件与审计对齐（Req: `requirements.md#req-13-6`；Impl: `apps/agent-api/src/anyagent_agent_api/app.py:541`；Module: `multi-agent`）
- [x] P2 梳理与 `/v1/responses` 的兼容性注意事项并落文档/测试（Req: `requirements.md#req-13-7`；Impl: `docs/_dev/multi-agent/responses-compat.md:1`；Module: `multi-agent`）
- [x] P0 修复 Multi-Agent 命名冲突：子 agent 标识统一为 `thread_id`（避免与 AgentSpec `agent_id` 混淆）（Req: `requirements.md#req-13-2`；Impl: `requirements.md:1111`；Module: `multi-agent`）
