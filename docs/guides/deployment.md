<!--
---
doc_kind: guide
status: stable
tags: ["deployment", "storage", "observability", "credential", "plugin", "tool-runtime", "sandbox"]
summary: 安装来源、部署形态、外置存储、日志观测、凭据后端、插件与独立 Tool Runtime 的运维配置入口。
audience: operator
---
-->

# 部署与运维配置

本文列出从本地 demo 走向生产时要做的决定和最常用的命令。环境变量、参数和默认值以代码为准，查询方式见 [README.md](README.md#以代码为准)。上手流程见 [getting-started.md](getting-started.md)。

## 1. 安装来源与可选依赖

`anyagent` 发布在 Yunxiao Packages 的 PyPI 仓库 `anyagent`。在包管理器里把该仓库配置为安装源；仓库密码放在本机、服务器或流水线的 secret 中，不要写进受版本控制的依赖文件。发布流程见 [release-checklist.md](../release-checklist.md)。

默认安装是轻量的，生产能力按需通过 extras 启用，可选项以 `packages/anyagent/pyproject.toml` 的 `[project.optional-dependencies]` 为准。最常用的组合：

```bash
uv pip install 'anyagent[postgres,redis]'
```

## 2. 部署形态

| 形态 | 命令 | 适用场景 |
|---|---|---|
| all-in-one | `anyagent serve` | 本地开发、单进程 demo；进程内 Tool Runtime |
| 拆分部署 | `anyagent agent-api serve` + `anyagent tool-runtime serve` | 水平扩容、独立的工具执行池或更强隔离 |

两种形态共用同一套 protocol contract。组件职责与推荐拓扑见 [system-components.md](../architecture/overview/system-components.md)，并发与幂等语义见 [stateless-agent-service-architecture.md](../architecture/runtime/stateless-agent-service-architecture.md)。

只有 `exec` 这类命令执行工具需要沙箱。`local-unsafe` 只用于可信的本地开发，生产使用 `opensandbox` 或 `external`，见 [sandbox-security.md](../security/sandbox-security.md)。

## 3. 外置存储

生产推荐 PostgreSQL 为主、Redis 为热层，并用 Redis 做会话锁：

```bash
POSTGRES_DSN=postgresql://anyagent:anyagent@127.0.0.1:5432/anyagent \
REDIS_DSN=redis://127.0.0.1:6379/0 \
STORAGE_PROFILE=postgres-redis \
POSTGRES_SCHEMA_POLICY=migrate \
anyagent serve --session-lock-backend redis
```

- `POSTGRES_SCHEMA_POLICY=migrate` 时，启动前先执行 `anyagent storage migrate`。
- 只配 PostgreSQL 不配 Redis 时，会话锁只在单实例内有效，`anyagent storage health` 会标出 `single_instance_only=true`，不能水平扩容。
- 保留时长、命名空间等其余变量见 `StorageSettings` / `ServerSettings`。

存储 profile 解析、数据模型、保留策略和锁语义见 [storage-minimal-design.md](../architecture/storage/storage-minimal-design.md)。

## 4. 日志与观测

```bash
LOG_FORMAT=json OBSERVABILITY_HTTP_URL=https://collector.example.com/ingest anyagent serve
```

结构化日志同时写入 telemetry store 和可选的 HTTP collector。Studio 通过 `/internal/observability/*` 查询 run、工具、错误和 trace，不读取日志文件；配置 PostgreSQL 外置存储后 telemetry 可跨进程、跨重启查询。接口与指标口径见 [studio-control-plane-and-observability.md](../architecture/control-plane/studio-control-plane-and-observability.md)，审计字段见 [audit-logging.md](../security/audit-logging.md)。

## 5. 凭据后端

`anyagent serve` 默认把凭据存在内存里，重启即丢失。生产环境用 `MCP_CREDENTIAL_STORE_BACKEND` 选择 env、file、Infisical、数据库或 Vault 后端；部署后用 `GET /admin/credentials/capabilities` 确认当前生效的后端、是否可写和缺少的依赖。后端语义见 [credential-vault.md](../security/credential-vault.md#34-运行时后端选择与能力查询)。

## 6. 插件

- 默认加载 `<workspace>/plugins`，也可用 `--plugin-root` 指定；加载失败默认拒绝启动，`--plugins-fail-open` 改为记录错误后继续。
- 插件被加载后，其工具还要加入目标 agent 的 `tools.requested_tool_names` 才对 agent 可见。
- 部署后用 `anyagent plugin catalog --admin-url <url> --admin-key <key>` 确认加载结果和工具来源。

加载规则见 [tool-runtime-contract.md](../architecture/tool-runtime/tool-runtime-contract.md#内置工具与插件加载)，插件契约见 [plugin-connector-contract-v1.md](../architecture/decisions/plugin-connector-contract-v1.md)。

## 7. 独立 Tool Runtime 的沙箱 workspace

拆分部署且使用 `sandbox.filesystem.persistence_mode=session_hot_cold` 时，独立 Tool Runtime 负责 per-session workspace 的恢复、休眠和快照，并通过 `/admin/sandbox/*` 提供排查接口。快照放 S3 需要 `anyagent[s3]`，元数据放 PostgreSQL、lease 放 Redis 需要对应 extras。组件与生命周期见 [sandbox-session-filesystem-design.md](../architecture/runtime/sandbox-session-filesystem-design.md#66-独立-tool-runtime-的管理接口与组装)。

## 8. 部署编排

本仓不提供部署模板。进程编排（systemd、Docker Compose、K8s 等）、外部服务的部署和网络策略由业务仓库负责，分工见 [framework-boundary.md](../architecture/overview/framework-boundary.md)。
