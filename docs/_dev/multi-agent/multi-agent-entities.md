# Multi-Agent v0 核心实体与存储结构（Draft）

对应需求：`requirements.md#req-13-2`、`requirements.md#req-13-4`

本文件目标：在落地系统工具（`spawn_agent/send_input/wait/...`）前，先固化 **thread/session 相关核心实体** 与 **v0 存储结构**，确保：

- 能支撑治理（`max_depth/max_threads/timeouts`）
- 能支撑最小可观测（`wait` 返回状态快照）
- v0 单实例可用（先 in-memory），后续能平滑迁移到持久化存储

## 1) 标识与术语

- `agent_id`：AgentSpec 配置标识（如 `main/legal/sales`），不等于 child thread 标识
- `thread_id`：Multi-Agent 编排中子 agent 的运行时标识（child thread id）
- `parent_thread_id`：触发 spawn 的父 thread id
- `session_key`：Gateway 会话绑定键（与 `agent_id` 一起用于构建 `session_partition_key`）

说明：
- 对外（模型可见）的系统工具全部使用 `thread_id` 来指代子 agent。

## 2) ThreadRecord（核心实体）

建议 v0 线程记录（ThreadRecord）至少包含：

- `thread_id: str`：全局唯一（推荐 `thr_<uuid>`）
- `parent_thread_id: str | None`：父线程；顶层 thread 为 `None`
- `root_thread_id: str`：根线程（方便治理与查询）
- `agent_id: str`：该 thread 绑定的 AgentSpec
- `depth: int`：root=0，child=parent+1（用于 `max_depth`）
- `status: Literal["queued","running","completed","failed","closed"]`
- `created_at_ms: int` / `updated_at_ms: int`
- `nickname: str | None`：可选 UI 名称
- `last_message: str | None`：用于 `wait` 返回的最小状态摘要（避免返回完整消息历史）

可选字段（v0 可留空，但应预留扩展位）：

- `session_source: str | None`：`cli/web/gateway/subagent.thread_spawn/...`
- `submission_seq: int`：用于 `send_input` 的提交号递增
- `run_timeout_seconds: int | None`：子线程单次 run 超时上限（Req: `requirements.md#req-13-4`）

## 3) InMemoryThreadStore（v0 存储结构）

v0 默认单实例实现建议使用内存存储（in-memory），在 Agent API 进程内维护：

- `threads_by_id: dict[thread_id, ThreadRecord]`
- `children_by_parent: dict[parent_thread_id, set[thread_id]]`
- `active_children_count_by_parent: dict[parent_thread_id, int]`（用于 `max_threads` 快速判断）

必须支持的原子操作（v0 先在单 event loop 内保证原子性）：

- `reserve_child_slot(parent_thread_id) -> bool`
- `create_thread(record) -> None`
- `set_status(thread_id, status, last_message?) -> None`
- `list_children(parent_thread_id) -> list[ThreadRecord]`
- `close_thread(thread_id) -> ok`

治理逻辑落点（v0）：

- `spawn_agent` 前：读取 parent.depth + 1 判定 `max_depth`
- `spawn_agent` 前：reserve slot 判定 `max_threads`
- `wait`：根据 `thread_id -> status` 返回快照；超时返回 `timed_out=true`

## 4) 迁移到持久化存储（后续）

当 `docs/architecture/storage/storage-minimal-design.md` 的存储选型继续演进后，可将 InMemoryThreadStore 的数据结构映射到表结构（示意）：

- `threads`（主表）：`thread_id` 主键，包含上述 ThreadRecord 字段
- `thread_edges`（关系表，可选）：`parent_thread_id -> child_thread_id`
- `submissions`（可选）：`thread_id + submission_id` 记录 send_input 投递历史（仅保存摘要）

v0 先保证接口稳定：
- `thread_id` 语义稳定
- `wait` 返回状态字段稳定
- 审计/事件对齐可在持久化后补强
