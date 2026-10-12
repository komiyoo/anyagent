# Guides 文档索引

本目录放面向使用者的操作指南：怎么安装、配置、启动、调用和部署 anyagent。设计原因与契约细节不在这里展开，指南中的每一节都链接到对应的 `architecture/` 或 `security/` 文档。

- [getting-started.md](getting-started.md)：零配置启动、`init` / `add`、单一 `anyagent.yaml`、调用接口、从 0.4 配置迁移
- [deployment.md](deployment.md)：安装来源、部署形态、环境变量对照、外置存储、凭据后端、插件、独立 Tool Runtime

## 以代码为准

指南写操作顺序、常用命令和取舍。字段与默认值以代码为准。只设环境变量时的对照表在 [deployment.md](deployment.md#3-只设环境变量)，占位符真源是 `builtin_defaults`。其余查询入口：

| 要查的信息 | 真源 |
|---|---|
| CLI 子命令与参数 | `anyagent <command> --help`，定义在 `packages/anyagent/src/anyagent/cli/` |
| `anyagent.yaml` 字段 | `packages/anyagent/src/anyagent/config/schema.py` 的 `WorkspaceConfig` |
| 环境变量占位符 | `packages/anyagent/src/anyagent/config/defaults.py` 的 `builtin_defaults`。运维对照表见 [deployment.md](deployment.md#3-只设环境变量) |
| `agent.yaml` 字段 | `packages/anyagent/src/anyagent/config/agents.py` 的 `AgentSpec` |
| 由生效配置派生的 server / storage / Tool Runtime 对象 | `packages/anyagent/src/anyagent/server/config/settings.py` 的 `ServerSettings`、`packages/anyagent/src/anyagent/storage/settings.py` 的 `StorageSettings`、`packages/anyagent/src/anyagent/tool_runtime/settings.py` 的 `ToolRuntimeSettings`。这三个模型不读进程环境 |
| 日志与观测环境变量 | 配置键 `observability.*`，占位符见 `builtin_defaults` |
| 可选依赖 extras | `packages/anyagent/pyproject.toml` 的 `[project.optional-dependencies]` |
| Agent Server HTTP 接口与模型 | `uv run --project packages/anyagent python scripts/export_protocol_schema.py --format openapi`，来源是 `anyagent.protocol.schema_export` |
| 独立 Tool Runtime HTTP 接口 | 运行中 Tool Runtime 的 `/openapi.json`，路由注册在 `packages/anyagent/src/anyagent/tool_runtime/server.py` |
| 凭据后端的当前能力 | 运行中服务的 `GET /admin/credentials/capabilities` |
| 已加载的插件与工具来源 | `GET /admin/plugins/catalog` 或 `anyagent plugin catalog` |
| workspace 配置是否有效 | `anyagent doctor --json` |
| 存储后端连通性 | `anyagent storage health` |
| SDK 用法 | 可运行示例 `tests/acceptance/sdk/acceptance_anyagent_client_surface_smoke.py` |
