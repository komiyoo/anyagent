# 安全与合规 TODO

对应需求：`requirements.md#req-8`

## 目标

- 明确并落实对外接口鉴权、工具执行安全边界、凭证管理、审计与合规要求。

## 里程碑（Milestones）

- M1：鉴权/权限模型清晰 + 默认拒绝
- M2：sandbox 工具最小权限与隔离到位
- M3：审计与告警可用
- M4：Credential Vault 凭证管理体系落地

## 任务（Tasks）

- [x] P0 明确威胁模型与外部输入校验边界（Req: `requirements.md#req-8`；Impl: `docs/security/security-threat-model.md:1`；Module: `docs`）
- [x] P0 落地 sandbox 工具最小安全要求与默认策略（Req: `requirements.md#req-5-5`，`requirements.md#req-8`；Impl: `docs/security/sandbox-security.md:1`, `apps/tool-runtime/src/anyagent_tool_runtime/http/app.py:36`；Module: `tool-runtime/docs`）
- [x] P1 落地工具权限与策略（policy）体系（Req: `requirements.md#req-5-10`，`requirements.md#req-8`；Impl: `apps/tool-runtime/src/anyagent_tool_runtime/runtime/policy.py:13`, `docs/security/tool-policy.md:1`；Module: `tool-runtime/docs`）
- [x] P2 落地审计事件与敏感操作留痕（Req: `requirements.md#req-5-13`，`requirements.md#req-8`；Impl: `apps/tool-runtime/src/anyagent_tool_runtime/runtime/executors.py:55`, `docs/security/audit-logging.md:1`；Module: `tool-runtime/docs`）

### Credential Vault（v1 凭证管理）

- [x] P0 [needs-design] 完成 Credential Vault 设计方案（Req: `requirements.md#req-8`，`requirements.md#req-5-9`；Impl: `docs/security/credential-vault.md:1`；Module: `docs/security`）
- [x] P1 补充威胁模型：凭证管理相关信任边界与威胁面（Req: `requirements.md#req-8`；Impl: `docs/security/security-threat-model.md:1`；Module: `docs/security`）
- [x] P0 实现 CredentialStore 抽象层与 EnvBackend（Req: `requirements.md#req-8`；Impl: `apps/tool-runtime/src/anyagent_tool_runtime/runtime/credential_store.py:33`；Module: `tool-runtime`）
  - refs: `apps/tool-runtime/src/anyagent_tool_runtime/settings.py:20`
- [x] P0 实现 ToolCredentialSpec 扩展 ToolDefinition（Req: `requirements.md#req-5-9`；Impl: `packages/anyagent/src/anyagent/tool_runtime/models.py:12`；Module: `packages/anyagent`）
- [x] P0 实现 Router 凭证注入逻辑（execute 前 resolve + 注入 `_credentials`）（Req: `requirements.md#req-8`；Impl: `apps/tool-runtime/src/anyagent_tool_runtime/runtime/executors.py:57`；Module: `tool-runtime`）
  - refs: `apps/tool-runtime/src/anyagent_tool_runtime/http/app.py:34`
- [x] P1 实现 Admin API（set/delete/list-refs，独立 ADMIN_API_KEY 鉴权）（Req: `requirements.md#req-8`；Impl: `apps/tool-runtime/src/anyagent_tool_runtime/http/app.py:92`；Module: `tool-runtime`）
  - refs: `apps/tool-runtime/src/anyagent_tool_runtime/http/auth.py:43`
  - refs: `packages/anyagent/src/anyagent/protocol/credential_vault.py:8`
- [x] P1 实现 FileBackend（文件系统存储，chmod 600）（Req: `requirements.md#req-8`；Impl: `apps/tool-runtime/src/anyagent_tool_runtime/runtime/file_credential_store.py:27`；Module: `tool-runtime`）
  - refs: `apps/tool-runtime/src/anyagent_tool_runtime/http/app.py:41`
- [x] P1 改造飞书插件：从 `context["_credentials"]` 获取凭证，保留 `os.getenv()` 回退（Req: `requirements.md#req-8`；Impl: `plugins/feishu/plugin.py:122`；Module: `plugins/feishu`）
  - refs: `plugins/feishu/plugin.py:186`
- [x] P1 实现凭证操作审计事件（set/delete 记录 credential_id + actor + scope）（Req: `requirements.md#req-5-13`，`requirements.md#req-8`；Impl: `apps/tool-runtime/src/anyagent_tool_runtime/http/app.py:95`；Module: `tool-runtime`）
- [x] P2 实现 CLI 管理命令（`anyagent credential set/list/delete/import`）（Req: `requirements.md#req-8`；Impl: `packages/anyagent/src/anyagent/cli.py:61`；Module: `cli`）
  - refs: `packages/anyagent/pyproject.toml:15`
- [x] P2 实现 `admin.credential_set` 特权工具（个人级场景，core 类别，需 AgentSpec 显式 allow）（Req: `requirements.md#req-8`；Impl: `apps/tool-runtime/src/anyagent_tool_runtime/runtime/executors.py:310`；Module: `tool-runtime`）
  - refs: `apps/tool-runtime/src/anyagent_tool_runtime/runtime/policy.py:13`
  - refs: `packages/anyagent/src/anyagent/tool_runtime/registry.py:51`
- [x] P2 编写部署凭证注入脚本（`scripts/init-credentials.sh`）与 credentials.yaml 模板（Req: `requirements.md#req-8`；Impl: `scripts/init-credentials.sh:1`；Module: `scripts`）
  - refs: `scripts/credentials.yaml.template:1`
- [x] P2 sandbox 隔离环境凭证隔离验证（确认 sandbox 容器/VM 不挂载凭证环境变量）（Req: `requirements.md#req-5-5`，`requirements.md#req-8`；Impl: `apps/tool-runtime/src/anyagent_tool_runtime/http/app.py:80`；Module: `tool-runtime`）
  - refs: `packages/anyagent/src/anyagent/tool_runtime/plugins.py:16`

### v2 规划（暂不实现）

- [ ] P3 [v2] 实现 DatabaseBackend（PostgreSQL 加密列存储）（Req: `requirements.md#req-8`；Module: `tool-runtime`）
- [ ] P3 [v2] 实现 VaultBackend（对接 HashiCorp Vault / AWS Secrets Manager）（Req: `requirements.md#req-8`；Module: `tool-runtime`）
- [ ] P3 [v2] 实现 session 级临时凭据 scope（CredentialScope.level=session）（Req: `requirements.md#req-8`；Module: `tool-runtime`）
- [ ] P3 [v2] 实现凭证轮转与过期机制（expires_at + rotate_before）（Req: `requirements.md#req-8`；Module: `tool-runtime`）
- [ ] P3 [v2] 实现凭证审计日志持久化（写入审计表，支持合规审查）（Req: `requirements.md#req-5-13`，`requirements.md#req-8`；Module: `tool-runtime`）

## 决策 & 争议点

- [x] Credential Vault 架构选型：方案 A（Tool Runtime 内置 CredentialStore + 注入）vs 方案 B（AI Gateway 代理）→ 选择方案 A（关联：`requirements.md#req-8`；决策记录：`docs/security/credential-vault.md#0.3`）
- [x] Admin API 是否独立服务还是嵌入 Tool Runtime：v1 继续嵌入，v2 满足规模阈值再拆分（关联：`requirements.md#req-8`；Impl: `docs/architecture/decisions/tool-runtime-federation-v0.md:1`；Module: `architecture/security`）

## 参考

- `requirements.md`
- `docs/security/credential-vault.md`（Credential Vault 完整设计）
- `docs/security/security-threat-model.md`（威胁模型，含凭证管理威胁分析）
