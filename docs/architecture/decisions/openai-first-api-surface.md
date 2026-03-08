<!--
---
doc_kind: architecture
status: stable
tags: ["responses-api", "sdk", "compatibility", "adr"]
summary: 明确 anyagent 的对外接口策略：OpenAI Responses API first；AnyAgent Client SDK 以单一 `AnyAgent` 入口、`client.openai/client.async_openai` 主路径与超集命名空间承载增强能力。
req: ["requirements.md#req-4-1", "requirements.md#req-9-1"]
---
-->

# ADR: OpenAI First API Surface + AnyAgent SDK Superset（资源型命名空间）

Status: Accepted
Date: 2026-03-05
Updated: 2026-03-05
Scope: Agent API / SDK / 接入规范

## 背景

当前仓库同时提供：

- 外部接口：`POST /v1/responses`（OpenAI Responses 兼容）
- AnyAgent 自有能力：`/internal/events/*`、`/internal/skills/list`、阶段性事件、replay 语义等

随着能力扩展，需要明确 "主接口 vs 超集接口" 的长期边界，避免调用方混用导致生态分裂。

## 决策

1. 对外主契约以 **OpenAI Responses API + OpenAI 官方 SDK** 为第一优先级。
2. AnyAgent Client SDK 定位为 **超集**，采用 **资源型命名空间模式**（类比 OpenAI 官方 SDK 的 `client.responses.*` 组织方式），而**非** local orchestration 模式（如 openai-agents-python 的 `Agent` dataclass + `Runner.run()`）：
   - anyagent 是 **server-side orchestration**（tool loop 在 Agent API 服务端执行），SDK 是远程服务的类型安全封装
   - 入口类 `AnyAgent` 维持单一表面；主兼容面通过 `client.openai` / `client.async_openai` 暴露
   - `responses` 的 `create/stream/retrieve/cancel` 主兼容面优先使用 OpenAI 官方 SDK（避免重复封装 fast-moving schema + HTTP 调用）
   - `client.responses` / `client.events` / `client.skills` 承载 anyagent 自有的 async helper 与超集能力
3. 新增外部 endpoint 时，优先遵循 OpenAI 语义与命名；仅在 OpenAI 未覆盖时新增 AnyAgent 增强语义。

### SDK 资源型命名空间设计

```python
client = AnyAgent(api_key="...", base_url="...")

# ── OpenAI 兼容面（优先使用官方 SDK）──
# sync
oa = client.openai
resp = oa.responses.create(...)           # POST /v1/responses
resp2 = oa.responses.retrieve(resp.id)    # GET /v1/responses/{id}

# async
oaa = client.async_openai
resp3 = await oaa.responses.create(...)   # POST /v1/responses
resp4 = await oaa.responses.retrieve(resp3.id)  # GET /v1/responses/{id}

# ── AnyAgent 的 async helper / 超集面 ──
payload = await client.responses.retrieve(resp.id)  # async helper
payload2 = await client.responses.cancel(resp.id)   # async helper

# internal endpoints（超集能力）
events = await client.events.list(response_id)  # GET /internal/events/list
async for ev in client.events.stream_typed(response_id):  # GET /internal/events/stream → StageEvent
    ...

skills = await client.skills.list(agent_id="main")  # GET /internal/skills/list

# ── 显式工厂（需要新实例时） ──
client.as_openai_client()                 # → 新的 openai.OpenAI
client.as_async_openai_client()           # → 新的 openai.AsyncOpenAI
```

关于 sync/async：

- `AnyAgent` 维持单一入口类，不拆 `AnyAgentSync` / `AsyncAnyAgent`，避免 API 面分裂。
- OpenAI 主兼容面通过 `client.openai` / `client.async_openai` 暴露，并做缓存复用；当调用方需要“明确获得一个新实例”时，使用 `as_openai_client()` / `as_async_openai_client()`。
- `client.responses.*` 仅承载 AnyAgent 自己补充的 async helper（`retrieve/cancel/retrieve_typed`），不复制 `create/stream` 等 fast-moving 官方 SDK 能力。
- `events/skills` 天然是异步调用（SSE/stream），因此 SDK 整体使用上仍建议 **async-first**；避免在同一条业务链路里混用 sync/async client，降低资源泄露与阻塞风险。

### 不选方案

1. **”AnyAgent 自定义外部 API 为主，OpenAI 兼容仅作适配层”**：不选，原因是削弱生态兼容与 SDK 可替换性。
2. **Local orchestration 模式（如 openai-agents-python）**：不选，原因是 anyagent 的架构是 server-side orchestration（tool loop、session、multi-agent 均在服务端），client 只是发请求 + 消费事件流，不在客户端执行 agent loop。`Agent` dataclass + `Runner.run()` 的模式与此拓扑不匹配。
3. **扁平单类（所有方法在一个 Client 类上）**：不选，原因是随着 endpoint 增长（events、skills、sessions、agents catalog 等）方法列表膨胀、语义分组不清晰。

### 可选增强 endpoint（已定稿）

- `GET /v1/responses/{response_id}`：查询 response 状态/最终结果。
- `POST /v1/responses/{response_id}/cancel`：请求取消 run（v0 best-effort）。

语义约束：

- 如果 run 已有 `final_response_json`，优先原样返回（保持与上游 schema 对齐）。
- 若无完整 final payload（例如 `in_progress` 或 best-effort `cancel`），仍返回 **OpenAI-compatible `Response` payload**（至少包含 OpenAI `Response` 的必填字段），确保 OpenAI 官方 SDK `responses.retrieve/cancel` 可解析。
- `cancel` 在 v0 是 best-effort：先保证存储层终态与事件流可收敛，不承诺强中断所有下游连接。

### 命名空间演进策略

- v0：`responses` + `events` + `skills`（对应当前全部 endpoint）
- 未来按需新增：`sessions`（会话管理）、`agents`（远程 catalog 查询）、`tools`（工具 manifest 查询）
- 每个命名空间是一个轻量类，共享 `_http` / `_base_url` / `_api_key` 引用，不引入额外连接或状态

## 落地影响

- `packages/anyagent/src/anyagent/agent_api_client.py`：重构为 `AnyAgent` 入口 + `Responses` / `Events` / `Skills` 子命名空间类
- Agent API 服务端 endpoint 不变
- Protocol 模型不变（`anyagent.protocol.*` 仍为 SSOT）
