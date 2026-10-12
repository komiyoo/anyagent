<!--
---
doc_kind: guide
status: stable
tags: ["deployment", "storage", "observability", "credential", "plugin", "tool-runtime", "sandbox"]
summary: 安装来源、部署形态、只设环境变量的配置对照、外置存储、凭据后端与插件的运维入口。
audience: operator
req: ["requirements.md#req-0-2"]
---
-->

# 部署与运维配置

本文列出从本地 demo 走向生产时要做的决定。上手流程和配置分层见 [getting-started.md](getting-started.md)。字段定义是 `packages/anyagent/src/anyagent/config/schema.py` 的 `WorkspaceConfig`。下表是内置默认里的环境变量占位符；凭据三个变量名按 0.5.0 的约定写，其余与 `packages/anyagent/src/anyagent/config/defaults.py` 的 `builtin_defaults` 一致。

未设置且占位符没有默认时，该键被去掉，改用 schema 默认。`${VAR:-default}` 在变量未设置或为空时使用默认。

## 1. 安装来源与可选依赖

`anyagent` 发布在 Yunxiao Packages 的 PyPI 仓库 `anyagent`。在包管理器里把该仓库配置为安装源；仓库密码放在本机、服务器或流水线的 secret 中，不要写进受版本控制的依赖文件。发布流程见 [release-checklist.md](../release-checklist.md)。

默认安装是轻量的。生产能力按需通过 extras 启用，可选项以 `packages/anyagent/pyproject.toml` 的 `[project.optional-dependencies]` 为准。

```bash
uv pip install 'anyagent[postgres,redis]'
```

## 2. 部署形态

| 形态 | 命令 | 适用场景 |
|---|---|---|
| all-in-one | `anyagent serve` | 单进程；进程内 Tool Runtime |
| 拆分部署 | `anyagent agent-api serve` + `anyagent tool-runtime serve` | 水平扩容、独立的工具执行池 |

`server.host` 默认 `127.0.0.1`，不读取 `HOST`。`anyagent serve` 在 host 不是 loopback（`127.0.0.1`、`localhost`、`::1`）且 `server.api_key` 为空时拒绝启动。对外监听时设置 `API_KEY` 或 `--api-key`。`anyagent dev` 在 key 为空时填入 `anyagent-dev-key`，供本机开发使用。

组件职责见 [system-components.md](../architecture/overview/system-components.md)。只有 `exec` 这类命令执行工具需要沙箱。`local-unsafe` 只用于可信的本地开发，生产使用 `opensandbox` 或 `external`，见 [sandbox-security.md](../security/sandbox-security.md)。

## 3. 只设环境变量

不写 yaml 时，进程环境（以及工作区 `.env` / `.env.local`，且不覆盖已有环境变量）驱动内置默认。同一 `PORT` 同时是 `server.port` 和 `tool_runtime.port` 的占位符，默认分别是 8787 和 8788；一旦设置 `PORT`，两处变成同一个值。

| 环境变量 | 配置键 | 未设置时 |
|---|---|---|
| `OPENAI_API_KEY` | `models.providers.openai.api_key`、`models.providers.openai_chat.api_key` | 去掉该键 |
| `OPENAI_BASE_URL` | 上述两个 provider 的 `base_url` | `https://api.openai.com/v1` |
| `ANTHROPIC_API_KEY` | `models.providers.anthropic.api_key` | 去掉该键 |
| `ANTHROPIC_BASE_URL` | `models.providers.anthropic.base_url` | `https://api.anthropic.com/v1` |
| `ANTHROPIC_VERSION` | `models.providers.anthropic.anthropic_version` | 去掉该键 |
| `GOOGLE_API_KEY`，空则 `GEMINI_API_KEY` | `models.providers.gemini.api_key` | 去掉该键 |
| `GEMINI_BASE_URL` | `models.providers.gemini.base_url` | `https://generativelanguage.googleapis.com/v1beta` |
| `PORT` | `server.port` | `8787` |
| `API_KEY` | `server.api_key` | 去掉该键 |
| `ADMIN_API_KEY` | `server.admin_api_key` | 去掉该键 |
| `AGENT_API_KEY` | `server.agent_api_key` | 去掉该键 |
| `CORS_ORIGINS` | `server.cors_origins` | 空列表。逗号分隔 |
| `STUDIO_DIR` | `server.studio_dir` | 去掉该键 |
| `STORAGE_PROFILE` | `storage.profile` | 去掉该键 |
| `STORAGE_MODE` | `storage.mode` | 去掉该键 |
| `EVENT_STORE_BACKEND` | `storage.event_store_backend` | 去掉该键 |
| `RUN_STORE_BACKEND` | `storage.run_store_backend` | 去掉该键 |
| `SESSION_STORE_BACKEND` | `storage.session_store_backend` | 去掉该键 |
| `SESSION_LOCK_BACKEND` | `storage.session_lock_backend` | 去掉该键 |
| `SESSION_LEASE_TTL_S` | `storage.session_lease_ttl_s` | `30` |
| `POSTGRES_DSN`，空则 `DATABASE_URL` | `storage.postgres_dsn` | 去掉该键 |
| `POSTGRES_SCHEMA` | `storage.postgres_schema` | `public` |
| `POSTGRES_SCHEMA_POLICY` | `storage.postgres_schema_policy` | `migrate` |
| `REDIS_DSN` | `storage.redis_dsn` | 去掉该键 |
| `MYSQL_DSN` | `storage.mysql_dsn` | 去掉该键 |
| `SQL_BACKEND_DIALECT` | `storage.sql_backend_dialect` | `auto` |
| `REDIS_NAMESPACE` | `storage.redis_namespace` | `anyagent` |
| `EVENT_STORE_RETENTION_S` | `storage.event_store_retention_s` | `7200` |
| `REPLAY_EVENT_STORE_RETENTION_S` | `storage.replay_event_store_retention_s` | `3600` |
| `RUN_STORE_RETENTION_S` | `storage.run_store_retention_s` | `7200` |
| `SESSION_STORE_RETENTION_S` | `storage.session_store_retention_s` | `86400` |
| `ROLLOUT_ROOT_DIR` | `storage.rollout_root_dir` | 去掉该键 |
| `ROLLOUT_ROTATE_MAX_BYTES` | `storage.rollout_rotate_max_bytes` | `0` |
| `ROLLOUT_ROTATE_MAX_AGE_SECONDS` | `storage.rollout_rotate_max_age_seconds` | `0` |
| `ROLLOUT_ROTATE_KEEP_FILES` | `storage.rollout_rotate_keep_files` | `16` |
| `CREDENTIAL_BACKEND` | `credentials.backend` | `none` |
| `CREDENTIAL_WRITABLE` | `credentials.writable` | `false` |
| `CREDENTIAL_FILE_ROOT` | `credentials.file.root` | `.anyagent/credentials` |
| `CREDENTIAL_POSTGRES_DSN` | `credentials.db.dsn` | 去掉该键 |
| `CREDENTIAL_POSTGRES_SCHEMA` | `credentials.db.schema` | `public` |
| `CREDENTIAL_ENCRYPTION_KEY` | `credentials.db.encryption_key` | 去掉该键 |
| `CREDENTIAL_DB_CREATE_SCHEMA` | `credentials.db.create_schema` | `false` |
| `VAULT_ADDR` | `credentials.vault.addr` | 去掉该键 |
| `VAULT_TOKEN` | `credentials.vault.token` | 去掉该键 |
| `VAULT_MOUNT` | `credentials.vault.mount` | `secret` |
| `VAULT_CREDENTIAL_ROOT_PATH` | `credentials.vault.credential_root_path` | `anyagent/credentials` |
| `INFISICAL_HOST` | `credentials.infisical.host` | `https://app.infisical.com` |
| `INFISICAL_UNIVERSAL_AUTH_CLIENT_ID` | `credentials.infisical.client_id` | 去掉该键 |
| `INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET` | `credentials.infisical.client_secret` | 去掉该键 |
| `INFISICAL_TOKEN` | `credentials.infisical.token` | 去掉该键 |
| `INFISICAL_PROJECT_ID` | `credentials.infisical.project_id` | 去掉该键 |
| `INFISICAL_ENVIRONMENT` | `credentials.infisical.environment` | 去掉该键 |
| `INFISICAL_CACHE_TTL_SECONDS` | `credentials.infisical.cache_ttl_seconds` | `60` |
| `INFISICAL_CREDENTIAL_ROOT_PATH` | `credentials.infisical.credential_root_path` | `/anyagent/credentials` |
| `INFISICAL_PATH_LAYOUT` | `credentials.infisical.path_layout` | `scoped` |
| `ALLOW_SANDBOX` | `sandbox.allow` | `false` |
| `SANDBOX_BACKEND` | `sandbox.backend` | `auto` |
| `SANDBOX_ISOLATION_MODE` | `sandbox.isolation_mode` | `disabled` |
| `SANDBOX_WORKSPACE_ROOT` | `sandbox.workspace_root` | `/workspace` |
| `SANDBOX_FILESYSTEM_PERSISTENCE_MODE` | `sandbox.filesystem_persistence_mode` | `ephemeral` |
| `SANDBOX_HOT_IDLE_TTL_S` | `sandbox.hot_idle_ttl_s` | `900` |
| `SANDBOX_COLD_RETENTION_S` | `sandbox.cold_retention_s` | `604800` |
| `SANDBOX_MAX_SNAPSHOT_BYTES` | `sandbox.max_snapshot_bytes` | `5368709120` |
| `OPENSANDBOX_BASE_URL` | `sandbox.opensandbox.base_url` | 去掉该键 |
| `OPENSANDBOX_API_KEY` | `sandbox.opensandbox.api_key` | 去掉该键 |
| `OPENSANDBOX_IMAGE` | `sandbox.opensandbox.image` | `ubuntu:24.04` |
| `OPENSANDBOX_TIMEOUT_S` | `sandbox.opensandbox.timeout_s` | `3600` |
| `OPENSANDBOX_CPU_LIMIT` | `sandbox.opensandbox.cpu_limit` | `1000m` |
| `OPENSANDBOX_MEMORY_LIMIT` | `sandbox.opensandbox.memory_limit` | `1Gi` |
| `OPENSANDBOX_PROXY_PORT` | `sandbox.opensandbox.proxy_port` | `44772` |
| `WORKSPACE_METADATA_BACKEND` | `sandbox.metadata_backend` | `auto` |
| `WORKSPACE_METADATA_ROOT_DIR` | `sandbox.metadata_root_dir` | 去掉该键 |
| `WORKSPACE_LEASE_BACKEND` | `sandbox.lease_backend` | `auto` |
| `WORKSPACE_LEASE_NAMESPACE` | `sandbox.lease_namespace` | `anyagent-tool-runtime` |
| `WORKSPACE_LEASE_TTL_MS` | `sandbox.lease_ttl_ms` | `60000` |
| `WORKSPACE_LEASE_WAIT_TIMEOUT_MS` | `sandbox.lease_wait_timeout_ms` | `2000` |
| `WORKSPACE_SNAPSHOT_BACKEND` | `sandbox.snapshot_backend` | `auto` |
| `WORKSPACE_SNAPSHOT_ROOT_DIR` | `sandbox.snapshot_root_dir` | 去掉该键 |
| `WORKSPACE_SNAPSHOT_S3_ENDPOINT` | `sandbox.snapshot_s3_endpoint` | 去掉该键 |
| `WORKSPACE_SNAPSHOT_S3_ACCESS_KEY` | `sandbox.snapshot_s3_access_key` | 去掉该键 |
| `WORKSPACE_SNAPSHOT_S3_SECRET_KEY` | `sandbox.snapshot_s3_secret_key` | 去掉该键 |
| `WORKSPACE_SNAPSHOT_S3_BUCKET` | `sandbox.snapshot_s3_bucket` | `anyagent-workspaces` |
| `WORKSPACE_SNAPSHOT_S3_SECURE` | `sandbox.snapshot_s3_secure` | `false` |
| `WORKSPACE_SNAPSHOT_S3_REGION` | `sandbox.snapshot_s3_region` | 去掉该键 |
| `PLUGIN_ROOTS` | `plugins.roots` | 空列表。逗号分隔 |
| `LOG_FORMAT` | `observability.log_format` | `text` |
| `LOG_LEVEL` | `observability.log_level` | `INFO` |
| `OBSERVABILITY_HTTP_URL` | `observability.http_url` | 去掉该键 |
| `OBSERVABILITY_HTTP_HEADERS` | `observability.http_headers` | 去掉该键 |
| `REPLAY_OBSERVABILITY_STDOUT` | `observability.replay_stdout` | 去掉该键 |
| `REPLAY_OBSERVABILITY_FILE` | `observability.replay_file` | 去掉该键 |
| `ALERT_WEBHOOK_URL` | `alerts.webhook_url` | 去掉该键 |
| `ALERT_WEBHOOK_FORMAT` | `alerts.webhook_format` | `json` |
| `ALERT_WEBHOOK_HEADERS` | `alerts.webhook_headers` | 去掉该键 |
| `TOOL_RUNTIME_BASE_URL` | `tool_runtime.base_url` | 去掉该键 |
| `TOOL_RUNTIME_INTERNAL_KEY` | `tool_runtime.internal_key` | 去掉该键 |
| `HOST` | `tool_runtime.host` | `127.0.0.1` |
| `PORT` | `tool_runtime.port` | `8788` |
| `MANIFEST_CACHE_TTL_SECONDS` | `tool_runtime.manifest_cache_ttl_seconds` | `5` |
| `TOOL_RUNTIME_PLUGIN_ROOTS` | `tool_runtime.plugin_roots` | 空列表。逗号分隔 |
| `TOOL_RUNTIME_PLUGINS_FAIL_OPEN` | `tool_runtime.plugins_fail_open` | `false` |
| `SANDBOX_ROOT_DIR` | `tool_runtime.sandbox_root_dir` | `/tmp/anyagent-tool-runtime-sandboxes` |
| `WORKSPACE_EVENT_BACKEND` | `tool_runtime.workspace_event_backend` | `memory` |
| `WORKSPACE_EVENT_ROOT_DIR` | `tool_runtime.workspace_event_root_dir` | 去掉该键 |
| `WORKSPACE_EVENT_MAX_BUFFER` | `tool_runtime.workspace_event_max_buffer` | `512` |

`plugins.builtin`、`plugins.fail_open` 和 `server.host` 没有对应的环境变量，需要时写 yaml 或 CLI。分层目录由 `SYSTEM_CONFIG_DIR`、`USER_CONFIG_DIR` 决定，它们不是配置键。

## 4. 外置存储

生产推荐 PostgreSQL 为主、Redis 为热层，并用 Redis 做会话锁：

```bash
POSTGRES_DSN=postgresql://anyagent:anyagent@127.0.0.1:5432/anyagent \
REDIS_DSN=redis://127.0.0.1:6379/0 \
STORAGE_PROFILE=postgres-redis \
POSTGRES_SCHEMA_POLICY=migrate \
anyagent serve --session-lock-backend redis
```

- `POSTGRES_SCHEMA_POLICY=migrate` 时，启动前先执行 `anyagent storage migrate`。
- 只配 PostgreSQL 不配 Redis 时，会话锁只在单实例内有效，`anyagent storage health` 会标出 `single_instance_only=true`。
- 凭据库的 DSN 是 `CREDENTIAL_POSTGRES_DSN`，不要复用上面的业务库变量名，除非你有意把它们配成同一个地址。

存储语义见 [storage-minimal-design.md](../architecture/storage/storage-minimal-design.md)。

## 5. 日志与观测

```bash
LOG_FORMAT=json OBSERVABILITY_HTTP_URL=https://collector.example.com/ingest anyagent serve
```

结构化日志写入 telemetry store，并可以发到 HTTP collector。Studio 通过 `/internal/observability/*` 查询，不读取日志文件。口径见 [studio-control-plane-and-observability.md](../architecture/control-plane/studio-control-plane-and-observability.md)，审计字段见 [audit-logging.md](../security/audit-logging.md)。

## 6. 凭据后端

`CREDENTIAL_BACKEND=none`（默认）时，进程内是内存凭据库，重启即丢失。生产用 `CREDENTIAL_BACKEND` 选择 `env`、`file`、`db`、`vault` 或 `infisical`，用 `CREDENTIAL_WRITABLE=true` 打开写入。名字不带 `-write`。Infisical 始终只读。file 的目录是 `CREDENTIAL_FILE_ROOT`。

```bash
CREDENTIAL_BACKEND=db \
CREDENTIAL_WRITABLE=true \
CREDENTIAL_POSTGRES_DSN=postgresql://anyagent:anyagent@127.0.0.1:5432/anyagent \
CREDENTIAL_ENCRYPTION_KEY=... \
anyagent serve
```

部署后用 `GET /admin/credentials/capabilities` 确认后端、是否可写和缺少的依赖。不启动 server 时：

```bash
anyagent credential list --local --workspace .
```

`set`、`delete`、`import` 同样接受 `--local`。省略时走 Admin API。语义见 [credential-vault.md](../security/credential-vault.md#34-运行时后端选择与能力查询)。

## 7. 插件

- 随包的 `chatwoot` 与 `lifecycle_echo` 默认不加载。在 `plugins.builtin` 里按名列入才启用。
- 工作区插件放在 `plugins.roots`。未设置时，存在 `<workspace>/plugins` 就会扫描它。`--plugin-root` 写入同一字段。
- 加载失败默认拒绝启动。`plugins.fail_open: true` 或 `--plugins-fail-open` 改为记录错误后继续。
- 插件被加载后，其工具还要加入目标 agent 的 `tools.requested_tool_names` 才对 agent 可见。
- `anyagent plugin catalog --admin-url <url> --admin-key <key>` 查看加载结果。

加载规则见 [tool-runtime-contract.md](../architecture/tool-runtime/tool-runtime-contract.md#内置工具与插件加载)。

## 8. 独立 Tool Runtime 的沙箱 workspace

拆分部署且 `sandbox.filesystem_persistence_mode=session_hot_cold` 时，独立 Tool Runtime 负责 per-session workspace 的恢复、休眠和快照。快照放 S3 需要 `anyagent[s3]`。组件见 [sandbox-session-filesystem-design.md](../architecture/runtime/sandbox-session-filesystem-design.md#66-独立-tool-runtime-的管理接口与组装)。

## 9. 部署编排

本仓不提供部署模板。进程编排、外部服务和网络策略由业务仓库负责，分工见 [framework-boundary.md](../architecture/overview/framework-boundary.md)。从 0.4 配置迁到本文件的步骤见 [getting-started.md](getting-started.md#8-从-04-配置迁移)。
