# 审计与留痕（v0：结构化日志）

对应需求：`requirements.md#req-5-13`、`requirements.md#req-8`

v0 阶段先以结构化日志满足“可追踪/可复盘”的最小线：对每次 tool execute 产生可关联的 `audit_ref`，并在日志中包含必要的链路字段，同时避免写入敏感信息。

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
  - 平台 token / AnyAgent API key / 内部 key
  - 原始 `arguments_json`（可能含 token、cookie、PII）
  - 原始工具输出（可能含敏感数据）
- 若确需调试：
  - 仅记录 schema 校验失败的摘要（错误 code/字段名）
  - 记录 `audit_ref` 作为后续审计系统/采样系统的关联键

## 3. `audit_ref` 语义

- `audit_ref` 是一次 tool 调用的稳定引用（随 idempotency 缓存而复用）
- 用于把 tool 执行日志、平台侧审计事件、以及后续持久化审计表关联起来

