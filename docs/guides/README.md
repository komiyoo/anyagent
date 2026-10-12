# Guides 文档索引

本目录放面向使用者的操作指南：怎么安装、配置、启动、调用和部署 anyagent。设计原因与契约细节不在这里展开，指南中的每一节都链接到对应的 `architecture/` 或 `security/` 文档。

- [getting-started.md](getting-started.md)：安装、生成 workspace、编辑 Agent Pack、启动服务、调用 OpenAI 兼容接口与 AnyAgent SDK、配置凭据与 MCP
- [deployment.md](deployment.md)：安装来源、部署形态、外置存储、日志观测、凭据后端、插件、独立 Tool Runtime 的沙箱 workspace

## 以代码为准

指南只写操作顺序、常用命令和取舍建议。参数、字段、环境变量、接口和默认值不在文档里抄写，直接查下表的真源：

| 要查的信息 | 真源 |
|---|---|
| CLI 子命令与参数 | `anyagent <command> --help`，定义在 `packages/anyagent/src/anyagent/cli/` |
| `agent.yaml` 字段 | `packages/anyagent/src/anyagent/config/agents.py` 的 `AgentSpec` |
| Agent Server 环境变量 | `packages/anyagent/src/anyagent/server/config/settings.py` 的 `ServerSettings`；存储相关见 `packages/anyagent/src/anyagent/storage/settings.py` 的 `StorageSettings` |
| 独立 Tool Runtime 环境变量 | `packages/anyagent/src/anyagent/tool_runtime/settings.py` 的 `ToolRuntimeSettings` |
| 日志与观测环境变量 | `packages/anyagent/src/anyagent/observability.py` |
| 可选依赖 extras | `packages/anyagent/pyproject.toml` 的 `[project.optional-dependencies]` |
| Agent Server HTTP 接口与模型 | `uv run --project packages/anyagent python scripts/export_protocol_schema.py --format openapi`，来源是 `anyagent.protocol.schema_export` |
| 独立 Tool Runtime HTTP 接口 | 运行中 Tool Runtime 的 `/openapi.json`，路由注册在 `packages/anyagent/src/anyagent/tool_runtime/server.py` |
| 凭据后端的当前能力 | 运行中服务的 `GET /admin/credentials/capabilities` |
| 已加载的插件与工具来源 | `GET /admin/plugins/catalog` 或 `anyagent plugin catalog` |
| workspace 配置是否有效 | `anyagent doctor --json` |
| 存储后端连通性 | `anyagent storage health` |
| SDK 用法 | 可运行示例 `tests/acceptance/sdk/acceptance_anyagent_client_surface_smoke.py` |
