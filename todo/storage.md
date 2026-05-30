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

## 当前状态

- 已完成条目已清理,历史记录请查看 Git。
- 已实现能力的长期口径见架构文档:
  - 存储最小设计、durable primary store + hot cache 语义与 backend 限制:`docs/architecture/storage/storage-minimal-design.md`
  - idempotency-key 与 cursor 语义统一规范(ADR):`docs/architecture/decisions/storage-idempotency-and-cursor-semantics.md`

## 待处理

- [ ] P2 加一个基线 bench 脚本,跑通典型 workspace 负载,产出回归参考数据(Req: `requirements.md#req-3-1`)

## 参考

- `docs/architecture/overview/roadmap.md` Phase 2
- `docs/architecture/storage/storage-minimal-design.md`
- `docs/architecture/runtime/stateless-agent-service-architecture.md`
