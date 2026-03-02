# 威胁模型与外部输入校验边界（v0）

对应需求：`requirements.md#req-8`

本文用于明确 AnyAgent v0 在 **Agent API / Tool Runtime / Gateway / Plugins / Sandbox** 之间的信任边界、外部输入面，以及每一层应承担的校验责任（谁校验什么、谁不信任谁）。

## 1. 系统角色与信任边界

### 1.1 外部调用方（不可信）

- 直连客户端（OpenAI SDK / curl / 自建服务）调用 Agent API：`POST /v1/responses`
- 平台用户输入（飞书/Discord/TG），经 Gateway 转发到 Agent API

原则：
- 外部输入默认不可信（包括 `tools[]`、`metadata`、`context` 里的任意字段）。
- “能推断出来的上下文”优先由服务端生成/裁剪后再下传到 Tool Runtime（避免 caller 注入策略）。

### 1.2 Agent API（受信任边界：业务入口）

职责（v0 已落地/需要持续保持一致）：
- 鉴权：`Authorization: Bearer <AGENT_API_KEY>`（拒绝缺失/错误 key）
- 会话分片：计算 `session_partition_key = "{agent_id}::{session_key}"`
- keyed serialization（单进程）：同一 `session_partition_key` 串行执行 agent loop（v0 单实例）
- 工具可见性：**永远以 Tool Runtime manifest 为权威**，不允许 caller 直接扩大工具暴露面

### 1.3 Tool Runtime（受信任边界：工具执行面）

职责（v0 强约束）：
- 内部鉴权：仅允许持有 `TOOL_RUNTIME_INTERNAL_KEY` 的调用方访问 `/internal/tools/*`
- 二次校验：不信任 Agent API/Gateway 的输入（尤其是 tool policy 与 tool name）
- 工具执行：对 arguments 做 schema 校验、执行超时控制、输出截断、错误分层
- 一致性：用 `toolset_version` 做乐观一致性校验（mismatch 返回 409）

### 1.4 Plugins / Sandbox（高风险边界）

- Plugins：视为“半可信代码”，必须被隔离在明确的 policy/审计框架下
- Sandbox：执行任意代码/命令属于高风险，需要最小权限隔离（详见 `requirements.md#req-5-5`）

## 2. 外部输入面清单（Input Surfaces）

### 2.1 Agent API：HTTP headers

- `Authorization`：必须存在且匹配 `AGENT_API_KEY`；**禁止落日志**
- `Idempotency-Key`：允许传入；可用于上游重试去重（不应包含敏感信息）
- `x-agent-id`：可选内部 header；若对外开放必须视为不可信

### 2.2 Agent API：`POST /v1/responses` JSON body

关键字段（均为不可信输入，需要最小校验）：
- `input`：可能是 string 或 list（需按 OpenAI Responses 兼容形态解析）
- `metadata`：必须为 object（若存在），其中：
  - `metadata.agent_id`：影响 AgentSpec 选择（必须存在且 exposed 才可用）
  - `metadata.session_key`：影响会话分片（缺失则生成临时会话）
  - `metadata.context`：用于 Tool Context，但必须裁剪/忽略 caller 的 `policy`
- `tools[]` / `tool_choice`：caller 提供的工具声明与选择提示
  - v0 约束：caller 的 `tools[]` 仅用于“希望披露哪些工具名”的信号，最终披露以 Tool Runtime manifest 为准

### 2.3 Tool Runtime：`/internal/tools/execute` JSON body

关键字段（不可信，必须严格校验）：
- `tool_name`：必须存在且在 registry 中
- `arguments_json`：必须能解析成 object，并通过 JSON Schema 校验
- `deadline_ms`：必须在合理范围内（避免长时间占用资源）
- `context`：用于 policy 判定（但 Tool Runtime 必须把它当成“提示”，并执行自己的 deny/allow 逻辑）

### 2.4 工具参数：URL / 文件 / 任意文本

典型高风险输入：
- `url`（例如 `core.web_fetch`）：存在 SSRF 风险
- 任意“文件路径/命令字符串”（sandbox 工具）：存在 RCE / 数据泄露风险
- 插件工具的外部资源标识（doc_id/chat_id/user_id）：存在越权风险

## 3. 校验责任划分（Validation Ownership）

### 3.1 Agent API 必须做的校验（Fail-fast）

- 请求体必须是 JSON object；`metadata` 必须是 object（若存在）
- `agent_id` 必须存在且 `exposed=true`
- `session_key` 缺失时必须生成临时值（仅用于该次 response，不承诺跨请求延续）
- caller 提供的 `metadata.context.policy` 必须忽略（不允许 caller 注入 allow/deny）
- caller 提供的 `tools[]`/`tool_choice` 必须经 Tool Runtime manifest 过滤；不在 allowlist 内的 tool_choice 必须拒绝

### 3.2 Tool Runtime 必须做的校验（Single Source of Truth）

- 内部鉴权：拒绝未授权调用
- `toolset_version` 一致性校验：不匹配返回 `toolset_version_mismatch`
- `tool_name` 存在性与分类校验：不在 registry 中直接 deny
- arguments schema 校验（JSONSchema）
- policy 二次校验：即使上游允许，也必须在 Tool Runtime 再判一次

### 3.3 SSRF 防护边界（v0 最小线）

原则：
- 任何“能发起网络请求的工具”都必须做 SSRF 防护（默认拒绝访问本机/内网/metadata）
- v0 可以先做“最小 denylist + 超时 + 重定向限制”，但必须在文档中明确不足（例如 DNS rebinding）并规划后续增强

## 4. 日志与敏感信息（Secrets）

必须满足：
- `Authorization`/内部 key/平台 token 不得写入日志与错误消息
- 若需要记录调试信息，必须用“可审计但不泄漏”的引用（例如 token hash 或 auth_ref）

## 5. 审计（v0 先定义字段口径）

对“工具执行”与“对外写操作”建议至少记录：
- `trace_id`（若有）
- `agent_id` / `session_key` / `session_partition_key`
- `response_id` / `tool_call_id` / `tool_name`
- 结果：`status`、错误 code、duration、是否 output_truncated

实现可以先落在结构化日志，后续再演进为持久化审计事件（见 `todo/security-compliance.md` 后续条目）。

