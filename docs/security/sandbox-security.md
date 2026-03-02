# Sandbox 工具最小安全要求与默认策略（v0）

对应需求：`requirements.md#req-5-5`、`requirements.md#req-8`

本文件用于把 sandbox（`sandbox.*`）类工具的安全底线写清，并把“默认禁用 + 显式开启闸门”的策略固化，避免在未隔离的情况下误开放高风险能力。

## 1. 默认策略（Default-Deny）

- Tool Runtime 默认 **不允许** sandbox 工具：
  - 配置项：`ALLOW_SANDBOX` 默认 `false`
  - policy 默认规则：无 allowlist 时，仅默认允许 `core/app`，对 `sandbox/channel` 默认拒绝

## 2. 显式开启闸门（Fail-fast）

当且仅当满足以下条件，才允许启用 sandbox：

- `ALLOW_SANDBOX=1`
- `SANDBOX_ISOLATION_MODE` 必须显式声明运行方式：
  - `container`：容器/VM 隔离（推荐）
  - `vm`：更强隔离（推荐）
  - `local_unsafe`：仅开发用途；明确存在 RCE/数据泄露风险

若 `ALLOW_SANDBOX=1` 但未显式设置可接受的 `SANDBOX_ISOLATION_MODE`，Tool Runtime 必须启动失败（fail-fast）。

## 3. 最小安全要求（v0 基线）

对任何 sandbox 工具实现（无论是 `sandbox.exec` 还是 `sandbox.python`），至少需要：

- 隔离执行：容器/VM/受限用户（禁止在 Tool Runtime 主进程权限下直接执行不受信任命令）
- 网络与文件系统策略：默认最小权限，策略化 allowlist
- 超时：必须支持硬超时 kill（`deadline_ms`）
- 输出限额：stdout/stderr 必须截断（`TOOL_OUTPUT_MAX_BYTES`）
- 审计：记录会话与调用链路（`agent_id/session_key/response_id/tool_call_id/tool_name`）
- 秘钥隔离：sandbox 侧禁止读取平台 token、AnyAgent API key、内部 key 等敏感信息

说明：
- 当前 v0 的 Tool Runtime 只提供 sandbox 的 **禁用默认策略与安全闸门**；具体 sandbox executor 的隔离落地应以此文档为验收基线推进。

