# 安全与合规 TODO

对应需求：`requirements.md#req-8`

## 当前状态

- 已完成条目已清理；历史记录请查看 Git。
- 当前仓库已补回最小安全主路径：`SandboxPolicy` 协议、会话级 exec 沙箱、Credential Admin API 与统一 observability/audit envelope。长期口径见 `docs/security/`、`docs/architecture/sandbox-session-filesystem-design.md`、`docs/architecture/studio-control-plane-and-observability.md`。

## 待处理

### v2 规划（暂不实现）

- [ ] P3 [v2] 实现 DatabaseBackend（PostgreSQL 加密列存储）（Req: `requirements.md#req-8`；Module: `tool-runtime`）
- [ ] P3 [v2] 实现 VaultBackend（对接 HashiCorp Vault / AWS Secrets Manager）（Req: `requirements.md#req-8`；Module: `tool-runtime`）
- [ ] P3 [v2] 实现 session 级临时凭据 scope（CredentialScope.level=session）（Req: `requirements.md#req-8`；Module: `tool-runtime`）
- [ ] P3 [v2] 实现凭证轮转与过期机制（expires_at + rotate_before）（Req: `requirements.md#req-8`；Module: `tool-runtime`）
- [ ] P3 [v2] 实现凭证审计日志持久化（写入审计表，支持合规审查）（Req: `requirements.md#req-5-13`，`requirements.md#req-8`；Module: `tool-runtime`）
