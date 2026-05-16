<!--
---
doc_kind: security
status: stable
tags: ["security", "audit", "logging", "tool-runtime", "sensitive-data"]
summary: 定义 tool_execute 审计留痕的结构化字段、脱敏与关联键（audit_ref/trace_id/response_id）。
req: ["requirements.md#req-5-13", "requirements.md#req-8"]
---
-->

# 审计与留痕（v0：结构化日志）

对应需求：`requirements.md#req-5-13`、`requirements.md#req-8`

v0 阶段先以结构化日志满足“可追踪/可复盘”的最小线：对每次 tool execute 产生可关联的 `audit_ref`，并在日志中包含必要的链路字段，同时避免写入敏感信息。

当前实现通过 `anyagent.protocol.observability.ObservabilityEvent` 统一封装审计/运行时事件，并由 `anyagent.observability.ObservabilityEmitter` fan-out 到 Python logging 与可选第三方 HTTP JSON collector。`ANYAGENT_LOG_FORMAT=json` 可开启本地 JSON 日志；`ANYAGENT_OBSERVABILITY_HTTP_URL` 可配置远端采集地址。

已纳入统一事件面的最小集合：

- `tool_execute.begin/done/cache_hit`
- `credential_audit`
- `mcp.server.connected`
- `mcp.server.connection_failed`
- `mcp.tools.listed`
- `mcp.tools.list_failed`
- `mcp.tool.conversion_failed`
- `mcp.tool.called`
- `mcp.server.idle_disconnected`
- `server.response.request_received`
- `server.response.replayed`
- `server.response.run_started`
- `server.response.stream.completed/cancelled/failed`
- `server.response.nonstream.completed/failed`

## 1. 关键字段（必须）

Tool Runtime 在 `tool_execute.begin/done/cache_hit` 日志里至少包含：

- `trace_id`（若有）
- `tenant_id`（若有）
- `agent_id`
- `session_key`
- `session_partition_key`
- `response_id`
- `tool_call_id`
- `tool_name`
- `status`
- `duration_ms`
- `output_truncated`
- `audit_ref`

## 2. 脱敏与限长（必须）

- 禁止在日志中写入：
  - 平台 token / anyagent API key / 内部 key
  - 原始 `arguments_json`（可能含 token、cookie、PII）
  - 原始工具输出（可能含敏感数据）
- 若确需调试：
  - 仅记录 schema 校验失败的摘要（错误 code/字段名）
  - 记录 `audit_ref` 作为后续审计系统/采样系统的关联键

## 3. `audit_ref` 语义

- `audit_ref` 是一次 tool 调用的稳定引用（随 idempotency 缓存而复用）
- 用于把 tool 执行日志、平台侧审计事件、以及后续持久化审计表关联起来
