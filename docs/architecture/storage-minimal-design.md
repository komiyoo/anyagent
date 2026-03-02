# 存储层最小设计（v0）

本文补齐 AnyAgent 在“无状态入口 + 可恢复执行”模式下所需的最小存储设计：技术选型、关键实体 schema、生命周期与一致性边界。它是 `requirements.md#req-3-1` 与 `docs/architecture/stateless-agent-service-architecture.md` 的落地补充。

## 1. 目标（Why）

- **支撑无状态 Ingress**：任意 Agent API 实例可接入请求、推流，不依赖本地内存状态。
- **支撑可恢复 Worker**：Worker 可被替换/重启，仍能从外置存储恢复会话与 run 状态。
- **支撑可靠性语义**：幂等（Idempotency）、断线补发（Event Store）、会话内串行（Lease Lock）。
- **支撑审计与排障**：对关键事件与外部写操作可追溯。

非目标（v0）：

- 不追求跨地域强一致的“分布式 actor”语义（未来可演进）。
- 不强制引入 Kafka/日志系统等重依赖（>1000 users 仍可先用 Postgres + Redis 组合跑稳）。

## 2. 逻辑组件与职责（What）

> 下面是“逻辑组件”。v0 可以把多个逻辑组件落到同一个物理存储里（例如都在 Postgres），但职责要清晰，避免把业务语义散落到多处。

- `Session Store`：会话快照（消息历史/游标/策略/上下文引用等）。
- `Run Store`：一次 `/v1/responses` 的元数据与状态机（started/completed/errored/aborted/timeout）。
- `Event Store`：增量事件日志（run 内单调递增 `seq`），用于 SSE 推流与断线补发。
- `Dedupe Store/Cache`：`idempotency_key -> run/response snapshot`（避免重试触发重复执行）。
- `Lock Service`：按 `session_partition_key` 的租约锁（TTL + 续租），保证会话内串行。
- （可选）`Event Bus`：发布订阅，把 Worker 产出的事件推给 Ingress/Platform Gateway（用于低延迟推流）。

## 3. 推荐技术选型（How）

### 3.1 推荐（生产默认）：PostgreSQL + Redis

- `PostgreSQL`：作为**持久化单一真源**（Session/Run/Event/Dedupe）。
- `Redis`：作为**低延迟的临时能力层**（Lease Lock、Event Bus PubSub、可选的 Dedupe 热缓存）。

为什么是这个组合：

- Postgres 负责“可查询、可审计、可保留”的持久数据（run/event/session）。
- Redis 负责“高频、低延迟、可过期”的状态（锁与事件广播），不把可靠性押在内存里。

### 3.2 允许（开发/单机）：SQLite（受限）+ 进程内实现

仅用于本地开发或单机 demo：

- SQLite 适合作为 Session/Run/Event 的持久化，但不适合作为多实例并发场景的锁与事件总线。
- 若采用 SQLite，`Lock Service/Event Bus` 必然退化（单进程/轮询），**不应作为生产方案**。

## 4. 数据模型（v0 最小 schema）

以下以 Postgres 为例给出建议字段（DDL 仅作参考，最终以服务端实现为准）。所有表建议预留 `tenant_id`（v0 可为空或固定值）。

### 4.1 sessions（Session Store：会话快照）

```sql
CREATE TABLE sessions (
  tenant_id               TEXT NULL,
  session_partition_key   TEXT NOT NULL, -- "{agent_id}::{session_key}"
  agent_id                TEXT NOT NULL,
  session_key             TEXT NOT NULL,

  snapshot_json           JSONB NOT NULL, -- messages/metadata/cursors/policy...
  snapshot_version        BIGINT NOT NULL DEFAULT 0,

  created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

  PRIMARY KEY (session_partition_key)
);
CREATE INDEX sessions_updated_at_idx ON sessions (updated_at);
```

说明：

- `snapshot_version` 用于乐观并发控制（CAS），避免并发写入覆盖（即使会话内串行也建议保留这条安全线）。
- 若要做多租户，可把主键改为 `(tenant_id, session_partition_key)`。

### 4.2 runs（Run Store：一次 responses 执行）

```sql
CREATE TABLE runs (
  tenant_id               TEXT NULL,
  response_id             TEXT NOT NULL, -- OpenAI Responses 的 response_id（AnyAgent 侧也作为 run_id）
  session_partition_key   TEXT NOT NULL,

  idempotency_key         TEXT NULL,     -- 来自请求头 Idempotency-Key
  stream                 BOOLEAN NOT NULL DEFAULT FALSE,

  status                  TEXT NOT NULL, -- started|completed|errored|aborted|timeout
  error_json              JSONB NULL,    -- 结构化错误（若有）

  final_response_json     JSONB NULL,    -- stream=false 或完成后可写入，供幂等直返
  last_event_seq          BIGINT NOT NULL DEFAULT 0,

  created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
  ended_at                TIMESTAMPTZ NULL,

  PRIMARY KEY (response_id)
);
CREATE UNIQUE INDEX runs_idempotency_key_uq ON runs (idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX runs_session_partition_idx ON runs (session_partition_key, created_at);
```

说明：

- `final_response_json` 是“幂等直返”的最小实现方式之一：命中 `idempotency_key` 时可直接返回 `200`（尤其是非流式请求）。
- `last_event_seq` 便于断线补发（也可不放在 runs 表，单独查询 events 的 max seq）。

### 4.3 events（Event Store：增量事件日志）

```sql
CREATE TABLE events (
  tenant_id               TEXT NULL,
  response_id             TEXT NOT NULL,
  session_partition_key   TEXT NOT NULL,

  seq                     BIGINT NOT NULL, -- run 内单调递增（从 1 开始）
  event_type              TEXT NOT NULL,   -- e.g. "response.output_item.added"
  payload_json            JSONB NOT NULL,  -- SSE data 的 JSON（或内部事件）

  created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

  PRIMARY KEY (response_id, seq)
);
CREATE INDEX events_response_seq_idx ON events (response_id, seq);
CREATE INDEX events_session_time_idx ON events (session_partition_key, created_at);
```

建议约束：

- `seq` 必须严格递增，且在重放时可还原为严格有序流。
- 事件体可以直接存 SSE 的 `data` JSON（对外协议事件）+ 内部事件并存；如要区分，增加 `stream_scope` 字段也可。

### 4.4 idempotency（Dedupe Store：幂等去重，可选独立表）

如果你不希望把幂等语义耦合进 `runs` 表，可单独建表（特别是要保留“accepted but not finished”的中间态时）：

```sql
CREATE TABLE idempotency_keys (
  tenant_id               TEXT NULL,
  idempotency_key         TEXT NOT NULL,
  response_id             TEXT NOT NULL,
  status                  TEXT NOT NULL, -- accepted|completed|errored|aborted|timeout
  response_snapshot_json  JSONB NULL,
  expires_at              TIMESTAMPTZ NOT NULL,

  created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

  PRIMARY KEY (idempotency_key)
);
CREATE INDEX idempotency_expires_idx ON idempotency_keys (expires_at);
```

最小规则：

- `idempotency_key` 必须有唯一约束（防止并发插入导致重复 run）。
- `expires_at` 必须存在，避免无限增长。

## 5. 生命周期与保留策略（TTL/Retention）

v0 推荐默认值（可配置）：

- `idempotency_key`：保留 `24h`（覆盖 webhook/客户端的重试窗口即可）。
- `events`：保留 `7d`～`30d`（用于断线补发与审计；按成本与合规调整）。
- `runs`：保留 `30d`～`180d`（至少要覆盖排障与审计窗口）。
- `sessions`：按“最后活跃时间”保留 `30d`～`90d`（或由业务明确删除策略）。

清理策略：

- 优先以 `tenant_id` 分片做定期清理（批量删除/归档），避免全表扫描。
- `events` 与 `runs` 建议可以按月分区（Partitioning），把清理从 DELETE 变为 DROP PARTITION（Phase 2+）。

## 6. 一致性与事务边界（Consistency）

### 6.1 事件写入与发布顺序

目标：既要低延迟推流，又要保证“断线可补发、不会丢事件”。

推荐顺序：

1. Worker 生成 event（含 `seq`）
2. **先写入 `Event Store`（持久化）**
3. 再发布到 `Event Bus`（Redis PubSub / NATS 等）

如果发布失败：

- 不影响持久化正确性；
- Ingress/Platform Gateway 可以从 `Event Store` 补拉（poll 或按游标拉取）。

### 6.2 Run 终态与幂等直返

推荐在同一 DB 事务里完成：

- 更新 `runs.status` 为终态（completed/errored/...）
- 写入 `runs.final_response_json`（如要支持非流式幂等直返）
- 更新 `sessions.snapshot_json`（会话快照推进）

并在事务提交后：

- 发布终态事件（`response.completed` / internal run end）

这样可以保证：即使 Ingress/Platform Gateway 断线或错过 PubSub，仍能从 DB 里恢复终态与补发事件。

## 7. Lock Service（Lease Lock）最小语义

v0 推荐用 Redis 实现 lease lock：

- key：`lease:{session_partition_key}`
- value：`{owner_id}`（Ingress/Worker 实例标识 + run_id）
- TTL：例如 `30s`
- 续租：Worker 每 `ttl/3` 续租一次

硬性要求：

- 续租失败必须快速中止执行并释放资源（避免双写/乱序）。
- 释放锁必须校验 owner_id（避免误删他人锁）。

如需 Postgres-only（不推荐作为首选）：

- 可以使用 advisory locks + 旁路 TTL（实现复杂度更高，v0 不建议先做）。

## 8. 与并发架构的关系

- `docs/architecture/stateless-agent-service-architecture.md` 描述的是“并发模型与执行路径”；本文提供“这些组件落到存储上如何设计”。
- v0 的关键验收点是：**命中幂等不会重复执行**、**断线可补发**、**会话内严格串行**。
