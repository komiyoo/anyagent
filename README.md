# anyagent（文档索引）

本目录用于沉淀 anyagent 的需求与架构设计，目标是支撑“多业务项目复用 + 多 agent + 多套专业 skills”的长期演进。

## 文档

- [requirements.md](requirements.md)
  - 对外：OpenAI Responses API 兼容面（`POST /v1/responses` + SSE）
  - 对内：Tool Runtime 协议、Gateway 插件模型、Skills 动态披露、Multi-Agent（Codex 风格）
- [todo/README.md](todo/README.md)
  - 按模块拆分的工程 TODO（每条任务可追溯到 `requirements.md#req-*`）
- [docs/stateless-agent-service-architecture.md](docs/stateless-agent-service-architecture.md)
  - 聚焦“服务侧并发与无状态部署”：keyed serialization、幂等、事件补发、慢消费者治理
  - 附带 OpenClaw / pi-mono 的概念对照（用于校准理解）
- [docs/storage-minimal-design.md](docs/storage-minimal-design.md)
  - 聚焦“存储落地”：Session/Run/Event/Dedupe/Lock 的最小 schema、保留策略与一致性边界
- [docs/architecture/responses-api-sdk-and-server.md](docs/architecture/responses-api-sdk-and-server.md)
  - 聚焦“接入侧 SDK + 服务侧 Agent Server”统一对齐 OpenAI Responses API，并给出泳道视角与模块边界

## 工具

- [scripts/anyagent_progress.py](scripts/anyagent_progress.py)
  - 默认只汇总 `todo/*.md` 进度：展示每个模块“下一条 TODO（第几条 + file:line）”，并提示已完成条目是否缺少 `Impl/Module` 证据字段
  - 仅在需要时用 `--scan-impl` 扫描实现线索（可选）

## 实现（Work In Progress）

- [apps/agent-api/README.md](apps/agent-api/README.md)
  - Python + uv：`POST /v1/responses`（含 `stream=true` SSE 透传）+ `/healthz`
- [apps/tool-runtime/README.md](apps/tool-runtime/README.md)
  - Python + uv：`/internal/tools/manifest|execute|cancel`
- [packages/anyagent](packages/anyagent)
  - SDK 包：`anyagent.*`（当前包含 `anyagent.tool_runtime`，其余子模块为占位骨架）

## 关键约定（便于跨项目复用）

- `agent_id`：同一套服务内不同 agent 的标识（persona/权限/skills/tool policy 组合）。
- `session_key`：平台侧线程/会话标识（飞书 thread、Discord thread、TG topic 等）。
- `session_partition_key`：并发分片键，建议固定为 `"{agent_id}::{session_key}"`。
- `Agent Packs`（配置目录即行为包）：业务项目/工作区内约定使用 `.agents/agents/<agent_id>/`，每个 agent 目录包含：
  - `agent.yaml`（结构化 AgentSpec：exposed/tools/skills/multiagent 等）
  - `AGENTS.md`（行为指令，注入到该 agent 的 run 中）
  - `skills/`（可选：该 agent 的私有技能）
- OpenAI Responses 请求的 `metadata` 建议携带：
  - `metadata.session_key`
  - `metadata.agent_id`
  - `metadata.skills`（JSON string 数组；仅当你希望显式指定 skills 时）
- skills 目录约定：业务项目内使用 `.agents/skills`（仓库内配置优先于用户级/系统级）。
