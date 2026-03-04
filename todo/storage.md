# Storage TODO

对应需求：`requirements.md#req-3-1`

## 目标

- 落地 AnyAgent 的最小存储原语（Session/Run/Event/Dedupe/Lock），支撑“无状态入口 + 可恢复执行”的并发架构与可靠性语义。

## 里程碑（Milestones）

- M1：存储选型与 schema 定稿（可本地跑通）
- M2：事件补发/幂等/锁租约的最小可用实现
- M3：保留策略/清理/观测与压测基线

## 任务（Tasks）

- [x] P0 补齐存储层最小设计方案文档（Req: `requirements.md#req-3-1`；Impl: `docs/architecture/storage-minimal-design.md:1`；Module: `storage`）
- [x] P0 确认 v0 存储技术选型（Postgres+Redis / Postgres-only）并固化配置项（Req: `requirements.md#req-3-1`；Impl: `packages/anyagent/src/anyagent/storage/settings.py:1`；Module: `storage`）
- [x] P0 落地 Session/Run/Event 表结构与索引（migration）（Req: `requirements.md#req-3-1`；Impl: `apps/agent-api/migrations/0001_init.sql:1`；Module: `storage`）
- [x] P0 落地 Dedupe（Idempotency-Key）写入/命中语义（Req: `requirements.md#req-7`；Impl: `apps/agent-api/src/anyagent_agent_api/app.py:368`, `apps/agent-api/src/anyagent_agent_api/storage/postgres.py:72`；Module: `storage`）
- [x] P0 落地 Lease Lock（TTL + 续租 + owner 校验）语义（Req: `requirements.md#req-7`；Impl: `apps/agent-api/src/anyagent_agent_api/storage/redis_lock.py:1`, `apps/agent-api/src/anyagent_agent_api/app.py:1339`；Module: `storage`）
- [x] P1 落地事件补发接口与游标语义（last_seq）（Req: `requirements.md#req-7`；Impl: `apps/agent-api/src/anyagent_agent_api/internal/events.py:1`；Module: `storage`）
- [x] P2 落地 retention/TTL 清理策略与运维脚本（Req: `requirements.md#req-3-1`；Impl: `apps/agent-api/src/anyagent_agent_api/storage/retention.py:1`；Module: `storage`）
- [x] P0 [needs-design] 对齐运行时术语与实体映射（`connection/session(thread)/run/turn/item/tool_call/event`）并固化字段级关联键规范（Req: `requirements.md#req-2`，`requirements.md#req-4-3-1`，`requirements.md#req-13-2`；Impl: `docs/architecture/agent-server-runtime-entities.md:1`；Module: `architecture/storage`）
- [x] P0 在未配置外部存储（`STORAGE_MODE=none`）时，按 `session_partition_key` 创建本地目录并追加写入 `rollout.jsonl`（append-only）（Req: `requirements.md#req-3-1`，`requirements.md#req-7`；Impl: `apps/agent-api/src/anyagent_agent_api/storage/runtime.py:185`, `apps/agent-api/src/anyagent_agent_api/storage/rollout.py:87`；Module: `storage`）
- [x] P0 定义并落地细粒度 rollout 事件模型（run/turn/item/tool_call/event），确保全链路可追溯与可 replay，且事件为 append-only（Req: `requirements.md#req-4-4`，`requirements.md#req-5-13`，`requirements.md#req-7`；Impl: `apps/agent-api/src/anyagent_agent_api/storage/rollout.py:111`, `apps/agent-api/src/anyagent_agent_api/app.py:465`；Module: `storage/agent-api`）
- [x] P0 落地“写入路径一次判重”机制：写前门控（事件指纹 + 幂等键）保证相同内容不写入，禁止“先写后校验”重写流程（Req: `requirements.md#req-5-11`，`requirements.md#req-7`；Impl: `apps/agent-api/src/anyagent_agent_api/storage/rollout.py:499`, `apps/agent-api/src/anyagent_agent_api/storage/inmemory.py:112`；Module: `storage`）
- [x] P1 提供 rollout 回放与观测工具（按 session/run 游标回放，支持 `last_seq`）用于排障与验收（Req: `requirements.md#req-4-4`，`requirements.md#req-7`，`requirements.md#req-9`；Impl: `apps/agent-api/src/anyagent_agent_api/storage/rollout_replay.py:1`, `apps/agent-api/pyproject.toml:22`；Module: `storage/agent-api`）
- [x] P0 落地 Session Store 读写接口与快照 schema（至少含 `runtime_config`、`resume_cursor.last_response_id`、`snapshot_version`）（Req: `requirements.md#req-3-1`，`requirements.md#req-4-6-1`，`requirements.md#req-4-6-2`；Impl: `apps/agent-api/src/anyagent_agent_api/storage/runtime.py:99`, `apps/agent-api/src/anyagent_agent_api/storage/models.py:29`, `apps/agent-api/src/anyagent_agent_api/storage/postgres.py:251`, `apps/agent-api/src/anyagent_agent_api/storage/inmemory.py:168`；Module: `storage`）
- [x] P0 落地会话快照 CAS 更新语义：run 终态提交时事务化更新 `runs + sessions`，避免并发覆盖（Req: `requirements.md#req-3-1`，`requirements.md#req-4-6-2`，`requirements.md#req-7`；Impl: `apps/agent-api/src/anyagent_agent_api/storage/postgres.py:136`, `apps/agent-api/src/anyagent_agent_api/app.py:614`；Module: `storage/agent-api`）
- [x] P1 在 `STORAGE_MODE=none` 下补齐本地恢复能力：从文件系统持久化载入 `runtime_config + resume_cursor`，与外部存储语义一致（Req: `requirements.md#req-4-6-1`，`requirements.md#req-4-6-2`，`requirements.md#req-7`；Impl: `apps/agent-api/src/anyagent_agent_api/storage/inmemory.py:174`, `apps/agent-api/src/anyagent_agent_api/storage/rollout.py:338`, `apps/agent-api/src/anyagent_agent_api/app.py:452`；Module: `storage/agent-api`）
- [x] P1 落地本地 rollout 文件保留与轮转策略（按大小/时间），避免 `STORAGE_MODE=none` 下无限增长（Req: `requirements.md#req-3-1`；Impl: `apps/agent-api/src/anyagent_agent_api/storage/rollout.py:90`, `apps/agent-api/src/anyagent_agent_api/storage/runtime.py:185`, `apps/agent-api/src/anyagent_agent_api/settings.py:36`, `scripts/acceptance_rollout_rotation_smoke.py:1`；Module: `storage`）
