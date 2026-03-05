# Tool Policy / Allowlist（v0）

对应需求：`requirements.md#req-5-10`、`requirements.md#req-8`

本文描述 anyagent v0 的最小 tool policy 体系：它如何在 **Tool Runtime** 层做 allow/deny，以及 **Agent API** 如何生成/传递 policy hint。

## 1. 设计原则

- Tool Runtime 是最终裁决者（Single Source of Truth）：不信任上游（Agent API/Gateway/外部 caller）的策略输入
- 默认最小暴露面：高风险类别（`sandbox`、`channel`）默认拒绝，除非显式 allow
- defense-in-depth：即使 tool 被 allow，具体 executor 仍需做资源/权限校验（例如平台 token、资源权限）

## 2. policy 的数据形态

policy 通过 `context.policy` 传入 Tool Runtime（字段名对齐 `requirements.md`）：

- `context.policy.allow_tools: list[str] | null`
- `context.policy.deny_tools: list[str] | null`

模式：

- 支持精确工具名：`core.web_fetch`
- 支持 glob：`feishu.*`、`sandbox.*`、`app.kb.*`

优先级：

- deny 优先于 allow

## 3. Tool Runtime 的裁决逻辑（v0 最小线）

在 Tool Runtime 中（`/internal/tools/manifest` 与 `/internal/tools/execute` 共用同一套逻辑）：

1. `deny_tools` 命中 → deny
2. sandbox 类工具：
   - 若 `ALLOW_SANDBOX=0` → deny
3. 若 `allow_tools` 非空：
   - 只有命中 allowlist 的工具才允许，其余 deny
4. 若 `allow_tools` 为空：
   - 默认允许 `core/app`
   - 默认拒绝 `channel/sandbox`

说明：

- `core.web_search` 在需求里被列为默认可允许的 core 工具之一，但当前 v0 仅内置 `core.web_fetch`；是否引入 search 取决于外部搜索能力与配额治理。

## 4. Agent API 的职责（policy hint 生成）

外部 caller 可能尝试通过 `metadata.context.policy` 注入 allow/deny；v0 规则：

- Agent API 必须忽略 caller 提供的 `metadata.context.policy`
- policy hint 的来源必须是服务端配置（AgentSpec / skills permissions 的编译结果）

最终由 Tool Runtime 再做一次裁决，防止“上游放大工具暴露面”。
