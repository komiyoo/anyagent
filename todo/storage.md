# Storage TODO

对应需求：`requirements.md#req-3-1`

## 目标

- 落地 AnyAgent 的最小存储原语（Session/Run/Event/Dedupe/Lock），支撑“无状态入口 + 可恢复执行”的并发架构与可靠性语义。

## 里程碑（Milestones）

- M1：存储选型与 schema 定稿（可本地跑通）
- M2：事件补发/幂等/锁租约的最小可用实现
- M3：保留策略/清理/观测与压测基线

## 任务（Tasks）

- [x] P0 补齐存储层最小设计方案文档（Req: `requirements.md#req-3-1`；Impl: `docs/storage-minimal-design.md:1`；Module: `storage`）
- [ ] P0 确认 v0 存储技术选型（Postgres+Redis / Postgres-only）并固化配置项（Req: `requirements.md#req-3-1`）
- [ ] P0 落地 Session/Run/Event 表结构与索引（migration）（Req: `requirements.md#req-3-1`）
- [ ] P0 落地 Dedupe（Idempotency-Key）写入/命中语义（Req: `requirements.md#req-7`）
- [ ] P0 落地 Lease Lock（TTL + 续租 + owner 校验）语义（Req: `requirements.md#req-7`）
- [ ] P1 落地事件补发接口与游标语义（last_seq）（Req: `requirements.md#req-7`）
- [ ] P2 落地 retention/TTL 清理策略与运维脚本（Req: `requirements.md#req-3-1`）

