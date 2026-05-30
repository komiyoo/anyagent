# 安全与合规 TODO

对应需求：`requirements.md#req-8`

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

- [x] DatabaseBackend 与 VaultBackend 是否需要同时支持，还是按部署形态二选一：同时支持，以 `MCP_CREDENTIAL_STORE_BACKEND=db-write|vault-write` 按部署形态选择。（Module: `tool-runtime`；Impl: `packages/anyagent/src/anyagent/server/security/credential_runtime.py:65`、`packages/anyagent/src/anyagent/server/security/credential_capabilities.py:135`）
- [x] 加密密钥本身的管理：preview 阶段仓内只接收 `CREDENTIAL_ENCRYPTION_KEY` 配置，不托管 KMS；生产密钥生命周期交由部署平台/KMS 管理。（Module: `tool-runtime`；Impl: `packages/anyagent/src/anyagent/server/security/credential_runtime.py:38`、`docs/security/credential-vault.md:294`）

## 参考

- `docs/architecture/overview/roadmap.md` Phase 3
- `docs/security/`
- `docs/architecture/runtime/sandbox-session-filesystem-design.md`
- `docs/architecture/control-plane/studio-control-plane-and-observability.md`
