# 安全与合规 TODO

对应需求：`requirements.md#req-8`

## 当前状态

- 已完成条目已清理；历史记录请查看 Git。
- 凭证管理等服务侧参考实现位于同级项目 `../anyagent-apps`；当前仓库保留需求、协议与待规划条目。

## 待处理

### v2 规划（暂不实现）

- [ ] P3 [v2] 实现 DatabaseBackend（PostgreSQL 加密列存储）（Req: `requirements.md#req-8`；Module: `tool-runtime`）
- [ ] P3 [v2] 实现 VaultBackend（对接 HashiCorp Vault / AWS Secrets Manager）（Req: `requirements.md#req-8`；Module: `tool-runtime`）
- [ ] P3 [v2] 实现 session 级临时凭据 scope（CredentialScope.level=session）（Req: `requirements.md#req-8`；Module: `tool-runtime`）
- [ ] P3 [v2] 实现凭证轮转与过期机制（expires_at + rotate_before）（Req: `requirements.md#req-8`；Module: `tool-runtime`）
- [ ] P3 [v2] 实现凭证审计日志持久化（写入审计表，支持合规审查）（Req: `requirements.md#req-5-13`，`requirements.md#req-8`；Module: `tool-runtime`）
