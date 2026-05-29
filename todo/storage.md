# Storage TODO

对应需求:`requirements.md#req-3-1`

## 目标

- 在保持 session/run/event 语义一致的前提下,让存储适配器具备分布式生产能力。

## 当前事实

- 共享存储模型 / contract / replay:`packages/anyagent/src/anyagent/storage/`
- Reference external adapters:in-memory、SQLite、PostgreSQL、Redis hot path
- Migration glue:`packages/anyagent/src/anyagent/server/migrations.py`
- 长期文档:`docs/architecture/storage/storage-minimal-design.md`

## 里程碑

- M1:replay contract 在 PG/Redis 组合下端到端通过
- M2:跨节点 session 一致性验收
- M3:典型负载基线 + 回归 bench

## 任务

- [x] P0 完成 PostgreSQL + Redis 组合下 session/run/event replay 的 contract test(Req: `requirements.md#req-3-1`; Impl: `tests/acceptance/server/acceptance_builtin_server_smoke.py:2064`; Module: `server-storage-acceptance`)
- [ ] P1 设计存储层 idempotency-key 与 cursor 语义的统一规范,落 ADR(Req: `requirements.md#req-3-1`)
- [ ] P2 加一个基线 bench 脚本,跑通典型 workspace 负载,产出回归参考数据(Req: `requirements.md#req-3-1`)

## 决策 & 争议点

- [ ] 是否需要在 contract 中区分 "hot path store" 与 "cold path store",还是仅以 adapter capability 描述

## 参考

- `docs/architecture/overview/roadmap.md` Phase 2
- `docs/architecture/storage/storage-minimal-design.md`
- `docs/architecture/runtime/stateless-agent-service-architecture.md`
