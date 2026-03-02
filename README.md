# AnyAgent（文档索引）

本目录用于沉淀 AnyAgent 的需求与架构设计，目标是支撑“多业务项目复用 + 多 agent + 多套专业 skills”的长期演进。

## 文档

- [requirements.md](/Users/ticoag/Documents/myws/clawers/AnyAgent/requirements.md)
  - 对外：OpenAI Responses API 兼容面（`POST /v1/responses` + SSE）
  - 对内：Tool Runtime 协议、Gateway 插件模型、Skills 动态披露、Multi-Agent（Codex 风格）
- [todo/README.md](/Users/ticoag/Documents/myws/clawers/AnyAgent/todo/README.md)
  - 按模块拆分的工程 TODO（每条任务可追溯到 `requirements.md#req-*`）
- [stateless-agent-service-architecture.md](/Users/ticoag/Documents/myws/clawers/AnyAgent/docs/stateless-agent-service-architecture.md)
  - 聚焦“服务侧并发与无状态部署”：keyed serialization、幂等、事件补发、慢消费者治理
  - 附带 OpenClaw / pi-mono 的概念对照（用于校准理解）

## 工具

- [scripts/anyagent_progress.py](/Users/ticoag/Documents/myws/clawers/AnyAgent/scripts/anyagent_progress.py)
  - 默认只汇总 `todo/*.md` 进度：展示每个模块“下一条 TODO（第几条 + file:line）”，并提示已完成条目是否缺少 `Impl/Module` 证据字段
  - 仅在需要时用 `--scan-impl` 扫描实现线索（可选）

## 实现（Work In Progress）

- [apps/agent-api-py/README.md](/Users/ticoag/Documents/myws/clawers/AnyAgent/apps/agent-api-py/README.md)
  - Python + uv：`POST /v1/responses`（含 `stream=true` SSE 透传）+ `/healthz`

## 关键约定（便于跨项目复用）

- `agent_id`：同一套服务内不同 agent 的标识（persona/权限/skills/tool policy 组合）。
- `session_key`：平台侧线程/会话标识（飞书 thread、Discord thread、TG topic 等）。
- `session_partition_key`：并发分片键，建议固定为 `"{agent_id}::{session_key}"`。
- OpenAI Responses 请求的 `metadata` 建议携带：
  - `metadata.session_key`
  - `metadata.agent_id`
  - `metadata.skills`（JSON string 数组；仅当你希望显式指定 skills 时）
- skills 目录约定：业务项目内使用 `.agents/skills`（仓库内配置优先于用户级/系统级）。
