# Security 文档索引

本目录承载安全相关的长期维护约束：威胁模型、沙箱安全、工具策略、审计留痕与凭证管理。

核心安全原则：**沙箱内自由，沙箱外隔离**。沙箱采用策略-后端分离架构（参考 Codex）。

入口：

- [security-threat-model.md](security-threat-model.md)：威胁模型与信任边界（首先读）
- [sandbox-security.md](sandbox-security.md)：沙箱执行环境策略（策略-后端分离 + OpenSandbox + 会话隔离 + exec tool）
- [../architecture/runtime/sandbox-session-filesystem-design.md](../architecture/runtime/sandbox-session-filesystem-design.md)：服务化会话文件系统设计（热冷分层、restore/checkpoint、对象存储治理）
- [tool-policy.md](tool-policy.md)：tool policy（允许/禁止/审计策略）
- [audit-logging.md](audit-logging.md)：审计留痕字段与日志约束
- [credential-vault.md](credential-vault.md)：凭证管理（Credential Vault）与安全落盘约束
