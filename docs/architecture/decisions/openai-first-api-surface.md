<!--
---
doc_kind: architecture
status: stable
tags: [“responses-api”, “sdk”, “compatibility”, “adr”]
summary: 明确 anyagent 的对外接口策略：OpenAI Responses API first；AnyAgent Client SDK 以资源型命名空间模式作为超集承载增强能力。
req: [“requirements.md#req-4-1”, “requirements.md#req-9-1”]
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

随着能力扩展，需要明确”主接口 vs 超集接口”的长期边界，避免调用方混用导致生态分裂。

## 决策

1. 对外主契约以 **OpenAI Responses API + OpenAI 官方 SDK** 为第一优先级。
2. AnyAgent Client SDK 定位为 **超集**，采用 **资源型命名空间模式**（类比 OpenAI 官方 SDK 的 `client.responses.*` 组织方式），而**非** local orchestration 模式（如 openai-agents-python 的 `Agent` dataclass + `Runner.run()`）：
   - anyagent 是 **server-side orchestration**（tool loop 在 Agent API 服务端执行），SDK 是远程服务的类型安全封装
   - 入口类 `AnyAgent`，通过子命名空间 `responses` / `events` / `skills` 组织能力
   - `responses` 命名空间委托 OpenAI 官方 SDK，不重复封装 HTTP 调用
   - `events` / `skills` 等命名空间承载 anyagent 独有的超集能力
3. 新增外部 endpoint 时，优先遵循 OpenAI 语义与命名；仅在 OpenAI 未覆盖时新增 AnyAgent 增强语义。

### SDK 资源型命名空间设计

```python
client = AnyAgent(api_key=”...”, base_url=”...”)

# ── OpenAI 兼容面（委托 OpenAI 官方 SDK）──
client.responses.create(...)              # POST /v1/responses (stream=false)
client.responses.create(..., stream=True) # POST /v1/responses (stream=true, SSE)
client.responses.retrieve(response_id)    # GET /v1/responses/{id}
client.responses.cancel(response_id)      # POST /v1/responses/{id}/cancel

# ── AnyAgent 超集面（内部观测 + 增强能力）──
client.events.list(response_id)           # GET /internal/events/list
client.events.stream(response_id)         # GET /internal/events/stream → SSEBlock
client.events.stream_typed(response_id)   # GET /internal/events/stream → StageEvent

client.skills.list(agent_id=”main”)       # GET /internal/skills/list

# ── 便捷方法 ──
client.as_openai_client()                 # → openai.OpenAI (base_url 已配置)
client.as_async_openai_client()           # → openai.AsyncOpenAI
```

### 不选方案

1. **”AnyAgent 自定义外部 API 为主，OpenAI 兼容仅作适配层”**：不选，原因是削弱生态兼容与 SDK 可替换性。
2. **Local orchestration 模式（如 openai-agents-python）**：不选，原因是 anyagent 的架构是 server-side orchestration（tool loop、session、multi-agent 均在服务端），client 只是发请求 + 消费事件流，不在客户端执行 agent loop。`Agent` dataclass + `Runner.run()` 的模式与此拓扑不匹配。
3. **扁平单类（所有方法在一个 Client 类上）**：不选，原因是随着 endpoint 增长（events、skills、sessions、agents catalog 等）方法列表膨胀、语义分组不清晰。

### 可选增强 endpoint（已定稿）

- `GET /v1/responses/{response_id}`：查询 response 状态/最终结果。
- `POST /v1/responses/{response_id}/cancel`：请求取消 run（v0 best-effort）。

语义约束：

- 如果 run 已有 `final_response_json`，优先原样返回（保持与上游 schema 对齐）。
- 若无完整 final payload，返回最小响应对象：`{id, object: “response”, status, error?}`。
- `cancel` 在 v0 是 best-effort：先保证存储层终态与事件流可收敛，不承诺强中断所有下游连接。

### 命名空间演进策略

- v0：`responses` + `events` + `skills`（对应当前全部 endpoint）
- 未来按需新增：`sessions`（会话管理）、`agents`（远程 catalog 查询）、`tools`（工具 manifest 查询）
- 每个命名空间是一个轻量类，共享 `_http` / `_base_url` / `_api_key` 引用，不引入额外连接或状态

## 落地影响

- `packages/anyagent/src/anyagent/agent_api_client.py`：重构为 `AnyAgent` 入口 + `Responses` / `Events` / `Skills` 子命名空间类
- Agent API 服务端 endpoint 不变
- Protocol 模型不变（`anyagent.protocol.*` 仍为 SSOT）
