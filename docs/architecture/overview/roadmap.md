<!--
---
doc_kind: architecture
status: stable
tags: ["roadmap", "architecture", "anyagent", "anyagent-apps"]
summary: anyagent architecture direction, current anchors, and runtime/SDK compatibility boundaries.
---
-->

# anyagent Architecture Direction

本文只记录 anyagent 的长期架构方向、当前事实锚点和关键边界。具体任务状态、执行清单和验收记录放在 `todo/*.md`、测试脚本或 release 记录中维护。

## 总体方向

anyagent 的目标是成为配置化、服务化的 AI Agent 基础设施：

- `anyagent serve` 从 agent workspace 启动 OpenAI Responses API compatible server。
- Agent 通过 `AGENTS.md`、`agent.yaml`、`mcp.json` 和 local skills 配置运行；agent loop 只能看到被披露的资源、policy 和 credential ref。
- Python built-in server 是当前 reference implementation；protocol/schema bundle 是 runtime、SDK、Studio 和测试之间的兼容锚点。
- 多语言 SDK 从同一份 protocol/schema 派生 wire model，再叠加语言惯用 resource namespace 和 helper。
- runtime 可替换性以 contract tests 和 conformance fixtures 为准，不以代码结构相似性为准。

## 当前事实锚点

| 领域 | 当前真源 | 已实现事实 |
|---|---|---|
| 协议 | `packages/anyagent/src/anyagent/protocol/`、`schema_export.py` | 导出 JSON Schema bundle、endpoint manifest、semantic rules 与 OpenAPI 3.1 document。 |
| Server | `packages/anyagent/src/anyagent/server/app.py` | 提供 `/v1/responses`、`/internal/*`、`/admin/*` typed endpoints。 |
| CLI | `packages/anyagent/src/anyagent/cli.py` | 提供 `serve`、`init`、`doctor`、config、storage、workspace 等 control-plane 入口。 |
| Python SDK | `packages/anyagent/src/anyagent/agent_api_client.py`、`anyagent.types` | 提供 OpenAI compatible client、events、agents、skills、tools、prompts、observability、admin 与 health namespaces。 |
| TypeScript SDK | `sdks/typescript/` | 从 protocol export 生成 schema/types，并通过 endpoint manifest 解析 schema-backed paths。 |
| Stage Events | `anyagent.protocol.events` | 覆盖 prompt context、model stream、tool planned/result、command planned/result 与 done 主路径。 |
| Storage | `anyagent.storage`、server storage adapters | 支持 in-memory、SQLite、PostgreSQL、Redis hot path 与 typed external SQL backend config。 |
| Tool Runtime | `anyagent.tool_runtime`、server tool endpoints | Core 承载 manifest/execute contract、credential resolver/admin-store assembly 与 standalone Tool Runtime 管理面。 |
| Credential | `anyagent.server.security.credential_*` | 提供 Env/File/Infisical read-only backend、admin credential CRUD 与 capability matrix。 |
| Sandbox | `anyagent.protocol.sandbox`、sandbox backend modules | 以 `SandboxPolicy`、`NetworkSandboxPolicy`、`ResourceLimits` 和 backend adapter 分离策略与执行。 |
| Studio | `packages/anyagent/studio/`、`packages/anyagent/src/anyagent/studio_static/` | 源码位于 package workspace，构建产物随 Python package 打包，消费 OpenAI Responses API、`/internal/*` 与 `/admin/*` typed API。 |

## 设计边界

### Protocol / Spec

- `anyagent.protocol.*` 是 Python 侧 wire contract 真源。
- schema bundle 是非 Python runtime、非 Python SDK 和 Studio 的可消费协议出口。
- 无法直接表达为 JSON Schema 的 Pydantic 语义进入 semantic rules。
- endpoint manifest 记录 endpoint id、method、path、request/response schema 与 streaming 语义。
- compatibility matrix 记录 server、protocol、SDK、Studio 的已实现兼容关系。

### Server Runtime

- Python built-in server 同时承担 reference server、开发 server 和协议验收基线。
- handler 在边界处消费 protocol model；runtime service 不依赖未校验的外部 shape。
- storage、credential、sandbox、tool runtime 通过 interface/adapter 分层，避免把 production backend 语义写死到 agent loop。
- 新 runtime 必须通过 Responses API、Stage Events、internal/admin API、Tool Runtime、storage/replay 的 contract tests 后才能替代生产主路径。

### SDK

- Python SDK 与 Python distribution 同包协作，但 public model facade 通过 `anyagent.types` 暴露。
- 非 Python SDK 位于 `sdks/<language>/`，生成层负责 wire DTO、serialization 和 runtime validation，手写层只承载语言惯用 helper。
- SDK 不复制协议字段，不直接依赖 server runtime、agent runtime 或 workspace loader。
- 每个 SDK 的 public surface 必须能追到 protocol schema、generated model 或 Python protocol model。

### Studio

- Studio 是 typed API consumer，不读取 server 内部 Python 模块。
- Studio 只能消费 OpenAI Responses API、`/internal/*` 与 `/admin/*` typed API。
- Studio 连接、agent catalog、workspace files、skills、MCP、tools、credentials、observability 和 debug 均通过 shared typed client facade 收口。
- Studio 页面职责、观测面与 skill/MCP/tool enablement 见 [studio-control-plane-and-observability.md](../control-plane/studio-control-plane-and-observability.md)。

### Apps Boundary

- `anyagent` 是 protocol、server、SDK、runtime primitives、Tool Runtime、credential/connector contract 与文档真源。
- `anyagent-apps` 消费已发布或已安装的 `anyagent`，承载业务 demo、部署模板、acceptance 入口和应用层文档。
- `anyagent-apps` 不恢复历史 `apps/agent-api`、`apps/tool-runtime` 或 `apps/studio` 服务壳作为框架真源。

## 兼容决策矩阵

| 决策点 | 当前锚点 | 长期约束 |
|---|---|---|
| 协议真源 | `anyagent.protocol.*` + schema bundle | 可独立版本化的 protocol/spec 制品必须保持同一 semantic rules。 |
| Server runtime | Python built-in server | 可替换 runtime 必须通过 reference conformance suite。 |
| Client SDK | Python SDK facade + TypeScript SDK scaffold | 多语言 SDK 必须从 protocol/spec 派生并通过 contract fixtures。 |
| 存储 | in-memory / SQLite / PostgreSQL / Redis adapters | 跨 runtime storage/replay contract 必须保持 session/run/event 语义一致。 |
| Tool Runtime | 进程内与 standalone Tool Runtime contract | manifest/execute、credential injection、policy enforcement 不绑定单一 runtime。 |
| Credential | Env/File/Infisical backend + admin store | Agent 只见 credential ref；secret 不通过 read API 回显。 |
| Sandbox | policy/backend adapter 分层 | backend 可替换，agent loop 只消费 `exec` tool 与 sandbox policy。 |
| Multi-Agent | runtime primitives 与 stage events | parent/child/root run、quota 与 event replay 语义必须可验收。 |
| 部署 | Python reference server + apps deployment templates | 部署模板不成为 protocol 或 runtime contract 真源。 |
