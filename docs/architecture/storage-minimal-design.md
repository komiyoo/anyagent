<!--
---
doc_kind: architecture
status: stable
tags: ["storage", "event-store", "dedupe", "lock", "postgres", "redis"]
summary: 给出无状态入口 + 可恢复执行所需的最小存储实体与一致性边界（Session/Run/Event/Dedupe/Lock）。
req: ["requirements.md#req-3-1"]
---
-->

# 存储层最小设计（v0）

本文补齐 anyagent 在“无状态入口 + 可恢复执行”模式下所需的最小存储设计：技术选型、关键实体 schema、生命周期与一致性边界。它是 `requirements.md#req-3-1` 与 [stateless-agent-service-architecture.md](stateless-agent-service-architecture.md) 的落地补充。

当前口径补充：

- 本文描述的 `Session/Run/Event/Dedupe/Lock` 语义属于 `anyagent` Core 的长期边界。
- `PostgreSQL + Redis` 的 runtime adapter 当前已开始迁入 `packages/anyagent/src/anyagent/storage/external/`；deployment wiring 与 migration/retention/replay CLI 仍主要落在 `anyagent-apps/apps/agent-api`。
- 后续收敛方向不是把整套 production backend 搬进 Core，而是把 store interfaces、状态模型与一致性语义回收到 Core，再让 `anyagent-apps` 继续承载 production adapters。
- 当前已落地的共享抽象位于 `packages/anyagent/src/anyagent/storage/`，`apps/agent-api` 已开始直接消费这些 records / contracts / runtime bundle。
- `/internal/events/*` 的 replay/list/stream helper 也已开始收敛到 `packages/anyagent/src/anyagent/storage/replay.py`。
- 会话准备与 snapshot 写回相关的共享编排 helper 已开始收敛到 `packages/anyagent/src/anyagent/agent_runtime/session_runtime.py`。
- 当前 `anyagent` 也已通过 `packages/anyagent/src/anyagent/storage/capabilities.py` 与 `/admin/storage/health` 暴露 reference/external backend capability matrix，用来明确 Core reference backend 边界与长期归属。
- MySQL 当前已先作为 typed contract (`MySQLDsn` / `ExternalSqlBackendConfig`) 进入 Core，为后续多 SQL backend 接入预留协议位。
- 共享 schema apply helper 当前已开始进入 `packages/anyagent/src/anyagent/storage/external/migrations.py`；但 migration / retention / rollout replay CLI 入口仍保留在 `anyagent-apps`。

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

### 2.1 归属边界

建议固定以下边界：

- 属于 `anyagent` Core 的部分：
  - `Session Store` / `Run Store` / `Event Store` / `Dedupe Store` / `Lock Service` 的抽象接口
  - `snapshot_version` / CAS / idempotency / replay cursor / `[DONE]` 等一致性语义
  - `STORAGE_MODE=none` 对应的 reference 行为
- 属于 `anyagent-apps` 的部分：
  - PostgreSQL / Redis backend 实现
  - 生产部署下的 lease / event bus / hot cache wiring
  - migration / retention / rollout replay 等运维命令

## 3. 推荐技术选型（How）

### 3.1 推荐（生产默认）：PostgreSQL + Redis

- **v0 决策（2026-03-02）**：选择 `PostgreSQL + Redis` 作为生产默认。
- 对应配置项（env）建议冻结为：
  - `POSTGRES_DSN`：Postgres 连接串（例如 `postgresql://user:pass@host:5432/anyagent`）
  - `POSTGRES_SCHEMA`：默认 `public`
  - `REDIS_DSN`：Redis 连接串（例如 `redis://host:6379/0`）
  - `REDIS_NAMESPACE`：默认 `anyagent`（避免共享 Redis 时 key 冲突）

- `PostgreSQL`：作为**持久化单一真源**（Session/Run/Event/Dedupe）。
- `Redis`：作为**低延迟的临时能力层**（Lease Lock、Event Bus PubSub、可选的 Dedupe 热缓存）。

说明：

- 这里的 “推荐生产默认” 指的是工作区当前的应用层部署选择，不代表 `anyagent` Core 必须内建一套 PG/Redis production backend。
- Core 应冻结这些后端所需的抽象与一致性语义；production adapters 继续可以由 `anyagent-apps` 提供。

为什么是这个组合：

- Postgres 负责“可查询、可审计、可保留”的持久数据（run/event/session）。
- Redis 负责“高频、低延迟、可过期”的状态（锁与事件广播），不把可靠性押在内存里。

### 3.1.1 读写顺序（PG 为主，Redis 为热层）

当同时启用 PostgreSQL 与 Redis 时，推荐固定为以下语义：

1. **写入**：先写 PostgreSQL（真源），再 best-effort 刷新 Redis（热层）。
2. **读取**：先查 Redis；若 miss，则查 PostgreSQL，并把结果回填到 Redis。
3. **过期**：Redis TTL 仅表示热数据失效；**不得**把 Redis 过期理解为业务数据删除。
4. **一致性边界**：
   - CAS / 唯一约束以 PostgreSQL 为准
   - Redis 写失败不应导致主事务回滚
   - Redis 可以重建，PostgreSQL 不能丢

这意味着：

- `Session Store` 的 `snapshot_version` 以 PostgreSQL 里的版本为真源；
- `Run Store` 的 `idempotency_key` 唯一性以 PostgreSQL 为真源；
- `Event Store` 的补发可以优先命中 Redis 热数据，miss 后回退 PostgreSQL。

当前落地顺序建议：

1. `Session Store` 先切到 PG 主 + Redis 热层（恢复语义最核心）
2. `Run Store` 再切到 PG 主 + Redis 热层（幂等与终态查询）
3. `Event Store` 最后切到 PG 主 + Redis 热层（事件体量最大，适合在前两者稳定后收口）

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

#### 4.1.1 `snapshot_json` 推荐结构（OpenAI Responses Provider）

为支持“连续会话无损恢复 + 会话参数稳定复用”，建议把 `snapshot_json` 结构收敛为：

```json
{
	"provider": "openai_responses",
	"runtime_config": {
		"model": "gpt-4.1-mini",
		"temperature": 0.2,
		"top_p": 1.0,
		"frequency_penalty": 0.0,
		"presence_penalty": 0.0,
		"reasoning": {
			"effort": "medium"
		}
	},
	"resume_cursor": {
		"last_response_id": "resp_xxx",
		"fallback_transcript_items": []
	},
	"last_run": {
		"response_id": "resp_xxx",
		"last_event_seq": 42,
		"updated_at_ms": 1760000000000
	}
}
```

字段语义：

- `runtime_config`：会话级默认运行参数；后续请求默认复用，仅在调用方显式传对应字段时做字段级 merge 更新。
- `resume_cursor.last_response_id`：OpenAI Responses 的首选恢复游标；下一次请求优先用 `previous_response_id + 本次增量 input` 继续会话。
- `resume_cursor.fallback_transcript_items`：当 `last_response_id` 不可用时的兜底重建材料（可按保留策略裁剪）。
- `last_run.*`：用于排障、验收与一致性检查，不参与业务语义判断。

### 4.2 runs（Run Store：一次 responses 执行）

```sql
CREATE TABLE runs (
  tenant_id               TEXT NULL,
  response_id             TEXT NOT NULL, -- OpenAI Responses 的 response_id（anyagent 侧也作为 run_id）
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

### 5.1 运维脚本（v0）

Agent API 提供一个 Postgres 清理脚本（默认 **plan-only**，不会写库；需要显式 `--apply` 才会执行）：

- `../anyagent-apps/apps/agent-api/src/anyagent_agent_api/storage/retention.py`
- CLI：`agent-api-retention`（见 `../anyagent-apps/apps/agent-api/pyproject.toml`）

执行示例：

- 预估下一批次影响（不写库）：`POSTGRES_DSN=... uv run --project ../anyagent-apps/apps/agent-api agent-api-retention`
- 实际执行（分批提交）：`POSTGRES_DSN=... uv run --project ../anyagent-apps/apps/agent-api agent-api-retention --apply`

最小语义：

- `Idempotency-Key TTL`：对已结束（`ended_at` 非空）的 runs，超过 TTL 后把 `runs.idempotency_key` 置空，避免唯一约束导致幂等键永久占用。
- `Events retention`：按 run 的 `ended_at` 批量删除对应 `events`（用于控制断线补发窗口与成本）。
- `Runs/Sessions retention`：按 `ended_at` / `updated_at` 批量删除历史数据。

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

### 6.3 Session Resume 的读-并-写顺序（必须）

对于 `POST /v1/responses`，推荐把会话恢复与配置合并统一成固定顺序：

1. 获取 `session_partition_key` 的 lease lock（会话内串行）。
2. 读取 `sessions.snapshot_json`（无记录则初始化空快照）。
3. 计算 `effective_runtime_config`：
   - 基于快照中的 `runtime_config`
   - 仅对请求中显式出现的受管字段做覆盖更新（`model/temperature/top_p/frequency_penalty/presence_penalty/reasoning`）
4. 组装首轮上游请求：
   - 若有 `resume_cursor.last_response_id`：使用 `previous_response_id + 本次增量 input`
   - 否则使用 `fallback_transcript_items + 本次增量 input`
5. run 完成后，在同一事务中写入：
   - `runs` 终态（`status/final_response_json/error_json`）
   - `sessions.snapshot_json`（更新 `runtime_config` + 新 `resume_cursor`）
   - `sessions.snapshot_version = snapshot_version + 1`
6. 提交事务后发布终态事件并释放锁。

备注：

- `STORAGE_MODE=none` 场景应保持等价语义（本地文件也要能恢复 `runtime_config + resume_cursor`），否则外置存储与本地模式行为会分叉。

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
