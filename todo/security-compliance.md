# 安全与合规 TODO

对应需求：`requirements.md#req-8`、`requirements.md#req-0-2`

## 当前状态

- 已完成条目已清理；历史记录请查看 Git。
- 当前仓库已补回最小安全主路径：`SandboxPolicy` 协议、会话级 exec 沙箱、Credential Admin API 与统一 observability/audit envelope。长期口径见 `docs/security/`、`docs/architecture/runtime/sandbox-session-filesystem-design.md`、`docs/architecture/control-plane/studio-control-plane-and-observability.md`。
- Credential v2 已落地 preview：PostgreSQL `DatabaseBackend`、HashiCorp Vault KV v2 `VaultBackend`、session scope、expires/rotate 生命周期字段、DB 审计表与 Alembic 迁移统一入口。长期口径见 `docs/security/credential-vault.md`。

## 里程碑

- M1：DatabaseBackend / VaultBackend 之一 GA，作为生产 credential 主路径替代（preview 已完成，GA 待真实部署验收）
- M2：Session 级临时凭据 + 轮转/过期语义在 reference runtime 通过 contract test（已完成）
- M3：审计日志持久化对接 observability envelope，可被合规审查工具消费（DB backend 已完成）

## 待处理（Phase 3 — Credential v2）

- [x] P1 [Phase 3] 实现 DatabaseBackend（PostgreSQL 加密列存储）（Req: `requirements.md#req-8`；Module: `tool-runtime`；Impl: `packages/anyagent/src/anyagent/server/security/credential_backends.py:335`、`packages/anyagent/src/anyagent/storage/alembic/versions/0002_credential_v2.py:20`）
- [x] P1 [Phase 3] 实现 VaultBackend（对接 HashiCorp Vault / AWS Secrets Manager 之一）（Req: `requirements.md#req-8`；Module: `tool-runtime`；Impl: `packages/anyagent/src/anyagent/server/security/credential_backends.py:552`）
- [x] P1 [Phase 3] 实现 session 级临时凭据 scope（CredentialScope.level=session）（Req: `requirements.md#req-8`；Module: `tool-runtime`；Impl: `packages/anyagent/src/anyagent/protocol/credential_vault.py:9`、`packages/anyagent/src/anyagent/server/security/credential_backends.py:320`）
- [x] P1 [Phase 3] 实现凭证轮转与过期机制（expires_at + rotate_before）（Req: `requirements.md#req-8`；Module: `tool-runtime`；Impl: `packages/anyagent/src/anyagent/protocol/credential_vault.py:31`、`packages/anyagent/src/anyagent/server/security/credential_backends.py:398`）
- [x] P1 [Phase 3] 实现凭证审计日志持久化（写入审计表，支持合规审查）（Req: `requirements.md#req-5-13`、`requirements.md#req-8`；Module: `tool-runtime`；Impl: `packages/anyagent/src/anyagent/server/security/credential_backends.py:498`、`packages/anyagent/src/anyagent/storage/alembic/versions/0002_credential_v2.py:41`）

## 决策 & 争议点

- [x] DatabaseBackend 与 VaultBackend 同时支持，用 `credentials.backend`（`CREDENTIAL_BACKEND=db|vault`）按部署选择。可写性是 `credentials.writable`（`CREDENTIAL_WRITABLE`），后端名不带 `-write`。（Req: `requirements.md#req-8`；Module: `anyagent.server.security`；Impl: `packages/anyagent/src/anyagent/server/security/credential_runtime.py:32`、`packages/anyagent/src/anyagent/config/schema.py:148`）
- [x] 加密密钥本身的管理：preview 阶段仓内只接收 `CREDENTIAL_ENCRYPTION_KEY` 配置，不托管 KMS；生产密钥生命周期交由部署平台/KMS 管理。（Module: `anyagent.server.security`；Impl: `packages/anyagent/src/anyagent/server/security/credential_runtime.py:159`）

## 已完成任务（0.5 凭据配置）

- [x] 凭据配置收成 `CredentialsConfig`。`build_credential_store` 与 `open_process_credential_store` 只接收配置对象。`backend=none` 时进程内落到内存库。（Req: `requirements.md#req-0-2`、`requirements.md#req-8`；Impl: `packages/anyagent/src/anyagent/config/schema.py:146`、`packages/anyagent/src/anyagent/server/security/credential_runtime.py:32`、`packages/anyagent/src/anyagent/server/security/credential_runtime.py:55`；Module: `anyagent.server.security.credential_runtime`）
- [x] 凭据环境变量是 `CREDENTIAL_BACKEND`、`CREDENTIAL_WRITABLE`、`CREDENTIAL_FILE_ROOT`。占位写在内置默认的 `credentials` 段。（Req: `requirements.md#req-0-2`；Impl: `packages/anyagent/src/anyagent/config/defaults.py:79`；Module: `anyagent.config`）
- [x] `credentials.runtime_env` 在启动时投影到进程环境。`config show` 显示环境变量名和 `credential:<id>`，不打印明文。（Req: `requirements.md#req-0-2`；Impl: `packages/anyagent/src/anyagent/server/runtime/workspace_env.py:44`、`packages/anyagent/src/anyagent/server/runtime/workspace_env.py:32`；Module: `anyagent.server.runtime.workspace_env`）
- [x] `anyagent credential set|list|delete|import --local` 不启动服务即可管理当前工作区后端。省略 `--local` 走 Admin API。（Req: `requirements.md#req-8`；Impl: `packages/anyagent/src/anyagent/cli/credential.py:19`；Module: `anyagent.cli.credential`）

## 参考

- `docs/architecture/overview/roadmap.md` Phase 3
- `docs/security/`
- `docs/architecture/runtime/sandbox-session-filesystem-design.md`
- `docs/architecture/control-plane/studio-control-plane-and-observability.md`
