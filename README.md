# anyagent（SDK 仓库）

本仓库当前聚焦 `packages/anyagent`：沉淀 anyagent 的协议模型、Client SDK、共享运行时能力与相关设计文档。

原先位于本仓库 `apps` 目录的可运行实践模板已迁到同级项目 `../anyagent-apps`，用于承载 `agent-api` / `tool-runtime` 场景集成、demo workspace、插件示例与集成验收。

## 文档

- [requirements.md](requirements.md)
  - 对外：OpenAI Responses API 兼容面（`POST /v1/responses` + SSE）
  - 对内：Tool Runtime 协议、Gateway 插件模型、Skills 动态披露、Multi-Agent（Codex 风格）
- [todo/README.md](todo/README.md)
  - 按模块拆分的工程 TODO（每条任务可追溯到 `requirements.md#req-*`）
- [docs/README.md](docs/README.md)
  - `docs/` 目录结构与文档分层约定（长期维护文档 vs 研发草案/笔记）
- [docs/architecture/stateless-agent-service-architecture.md](docs/architecture/stateless-agent-service-architecture.md)
  - 聚焦“服务侧并发与无状态部署”：keyed serialization、幂等、事件补发、慢消费者治理
  - 附带 OpenClaw / pi-mono 的概念对照（用于校准理解）
- [docs/architecture/storage-minimal-design.md](docs/architecture/storage-minimal-design.md)
  - 聚焦“存储落地”：Session/Run/Event/Dedupe/Lock 的最小 schema、保留策略与一致性边界
- [docs/architecture/responses-api-sdk-and-server.md](docs/architecture/responses-api-sdk-and-server.md)
  - 聚焦“接入侧 SDK + 服务侧 Agent Server”统一对齐 OpenAI Responses API，并给出泳道视角与模块边界
- [docs/architecture/apps-packages-boundary.md](docs/architecture/apps-packages-boundary.md)
  - `apps/*`（服务编排/demo）与 `packages/*`（协议/SDK/共享能力）的职责边界与收敛策略
- [docs/architecture/decisions/README.md](docs/architecture/decisions/README.md)
  - 架构决策记录（ADR）：接口策略、skills 策略、tool runtime 边界取舍
- [docs/architecture/engineering/ci-pipeline.md](docs/architecture/engineering/ci-pipeline.md)
  - CI 分层质量门（docs guardrails + offline smokes + optional online smokes）

## 工具

- [scripts/anyagent_progress.py](scripts/anyagent_progress.py)
  - 默认只汇总 `todo/*.md` 进度：展示每个模块“下一条 TODO（第几条 + file:line）”，并提示已完成条目是否缺少 `Impl/Module` 证据字段
  - 仅在需要时用 `--scan-impl` 扫描实现线索（可选）
- [tests/README.md](tests/README.md)
  - 测试/验收脚本索引（acceptance/smoke），按模块分层沉淀，避免平铺在 `scripts/`
- [scripts/docs/check.py](scripts/docs/check.py)
  - 检查 Markdown 断链与 `todo/*.md` 的 `Impl:` 证据引用是否漂移；可选 `--check-code-refs` 继续检查反引号里的 `path[:line]` 引用
- [scripts/docs/pack.py](scripts/docs/pack.py)
  - 按 tags/kind/status 打包“最小文档上下文列表”，支持渐进式披露（避免一次性加载过多无关文档）
- [scripts/docs/index.py](scripts/docs/index.py)
  - 生成 `docs/_manifest.txt`（纯文本 docs manifest），用于高效检索与按需加载（progressive disclosure）

## 实现

- [packages/anyagent](packages/anyagent)
  - SDK/共享能力包：`anyagent.protocol.*`、`anyagent.agent_runtime.*`、`anyagent.skills.*`、`anyagent.tool_runtime.*`
  - Client SDK：`AnyAgent` 资源型命名空间入口（`client.responses.*` / `client.events.*` / `client.skills.*`）

## 场景实践

- 同级项目 `../anyagent-apps`
  - 承载 `../anyagent-apps/apps/agent-api`、`../anyagent-apps/apps/tool-runtime`、`../anyagent-apps/examples/demo-workspace`、`../anyagent-apps/plugins/feishu` 与应用层验收脚本
  - 默认通过本地 path 依赖消费本仓库的 SDK：`../anyagent/packages/anyagent`

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
