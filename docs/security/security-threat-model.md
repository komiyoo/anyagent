# 威胁模型与外部输入校验边界（v0 + v1 凭证管理）

对应需求：`requirements.md#req-8`

本文用于明确 anyagent v0 在 **Agent API / Tool Runtime / Gateway / Plugins / Sandbox** 之间的信任边界、外部输入面，以及每一层应承担的校验责任（谁校验什么、谁不信任谁）。

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
- **凭证注入**（v1 新增）：Tool Runtime 是唯一可以 resolve 凭证明文的组件，在 handler 执行前自动注入，handler 执行后丢弃（详见 [credential-vault.md](credential-vault.md)）

### 1.4 Credential Vault / CredentialStore（v1 新增：凭证存储面）

- 职责：存储和 resolve 工具执行所需的凭证（API Key、Bearer Token、OAuth Client Secret 等）
- 信任关系：**仅 Tool Runtime 内部可调用 `resolve()`**，不暴露 HTTP get-value API
- 管理入口：Admin API（独立 `ADMIN_API_KEY` 鉴权）提供 set/delete/list-refs，不提供 get-value
- 存储后端：可插拔（环境变量 / 文件 chmod 600 / 数据库加密列 / 外部 Vault）

信任原则：

- Agent API、Model、Agent 均视为"不可信"——只能看到 `auth_ref`（引用），不能看到凭证明文
- 即使 Agent 拥有 `admin.credential_set` 工具（个人级场景），也**无法通过任何路径回读已存储的凭证**
- `_credentials` 字段仅在 Tool Runtime 进程内存中短暂存在（handler 调用期间），不回传给上游

### 1.5 Plugins / Sandbox（高风险边界）

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
- `context`：用于 policy 判定（但 Tool Runtime 必须把它当成”提示”，并执行自己的 deny/allow 逻辑）
- `context.auth_ref`：凭证引用，仅作为 CredentialStore resolve 的查找键（不得包含明文值）

### 2.4 Admin API：`/admin/credentials`（v1 新增）

- `POST /admin/credentials`：写入凭证。`value` 字段为明文输入，写入后不可读取
  - 鉴权：`ADMIN_API_KEY`（必须与 `AGENT_API_KEY` 不同）
  - `credential_id`：必须校验格式（建议 `[a-z0-9_]+`）
  - `scope`：必须校验 level 合法性；`agent` scope 必须提供有效 `agent_id`
- `GET /admin/credentials`：仅返回引用信息（credential_id / kind / scope / metadata），**禁止返回 value**
- `DELETE /admin/credentials/{id}`：删除凭证，必须记录审计事件

威胁面：

- Admin API 暴露在 Tool Runtime 端口上，必须通过独立 `ADMIN_API_KEY` 鉴权，防止 Agent 通过 SSRF 直接访问
- SSRF 基线防护（127.x / localhost / 内网）可阻止 Agent 工具对 Admin API 的间接调用

### 2.5 工具参数：URL / 文件 / 任意文本

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
- 凭证 resolve（v1）：根据 `ToolCredentialSpec` 声明和 `context.auth_ref` 从 CredentialStore resolve；required 凭证缺失时返回 `credential_not_found` 错误

### 3.3 SSRF 防护边界（v0 最小线）

原则：

- 任何“能发起网络请求的工具”都必须做 SSRF 防护（默认拒绝访问本机/内网/metadata）
- v0 可以先做“最小 denylist + 超时 + 重定向限制”，但必须在文档中明确不足（例如 DNS rebinding）并规划后续增强

## 4. 日志与敏感信息（Secrets）

必须满足：

- `Authorization`/内部 key/平台 token 不得写入日志与错误消息
- 若需要记录调试信息，必须用”可审计但不泄漏”的引用（例如 token hash 或 auth_ref）
- **凭证明文（`_credentials` 中的值）禁止写入任何日志**（v1 新增约束）
- 凭证操作（set/delete）必须记录审计事件，但审计事件中只记录 `credential_id`，不记录 `value`

## 5. 凭证管理威胁分析（v1 新增）

### 5.1 凭证泄漏路径与缓解

| 威胁路径 | 风险等级 | 缓解措施 |
|---|---|---|
| Agent 通过 sandbox 工具执行 `env`/`printenv` 读取环境变量 | 高 | sandbox 隔离容器不挂载凭证环境变量；`ALLOW_SANDBOX` 默认关闭 |
| Agent 构造 HTTP 请求调用 Admin API | 高 | SSRF 防护拒绝 127.x/localhost；Admin API 使用独立 `ADMIN_API_KEY` |
| Agent 指示工具将凭证写入工具输出（如 `echo $TOKEN`） | 中 | 输出截断 + 审计；sandbox 隔离环境不含凭证 |
| 插件代码 bug 将 token 泄漏到工具输出 | 中 | 输出审计 + 插件代码审查流程（v2） |
| 凭证文件被未授权进程读取 | 中 | FileBackend 文件权限 `chmod 600`；容器最小权限用户 |
| Admin API 请求被中间人截获 | 中 | 生产环境强制 HTTPS；内网部署可用 mTLS |
| CredentialStore 后端被直接访问（DB/文件） | 中 | DB 加密列；文件权限；Vault ACL（v2） |
| `_credentials` 在 handler 异常时被序列化到错误信息 | 低 | Tool Runtime 的 catch-all 错误处理不得序列化 context 内容 |

### 5.2 凭证 scope 越权

- `agent` scope 凭证必须验证当前执行的 `agent_id` 匹配
- `global` scope 凭证被所有 Agent 共享，属于预期行为（企业级管理员可控）
- Tool Runtime 在 resolve 时必须执行 scope 匹配逻辑，不依赖上游传入的 scope 信息

### 5.3 `admin.credential_set` 工具的特殊风险（个人级场景）

- 该工具允许 Agent 写入凭证，存在 Agent 被 prompt injection 攻击后写入恶意凭证的风险
- 缓解：该工具必须是 `core` 类别且需要 AgentSpec 显式 allow；默认不开启
- 缓解：set 操作记录完整审计（who/when/credential_id），人类可事后审查
- 缓解：凭证覆盖写入时记录 warning 级审计事件

## 6. 审计（v0 先定义字段口径 + v1 凭证审计扩展）

对“工具执行”与“对外写操作”建议至少记录：

- `trace_id`（若有）
- `agent_id` / `session_key` / `session_partition_key`
- `response_id` / `tool_call_id` / `tool_name`
- 结果：`status`、错误 code、duration、是否 output_truncated

实现可以先落在结构化日志，后续再演进为持久化审计事件（见 `todo/security-compliance.md` 后续条目）。

v1 新增审计字段（凭证操作）：

- `credential_id`：被操作的凭证标识
- `operation`：`set` / `delete` / `resolve`
- `scope`：凭证作用域（level + agent_id）
- `actor`：操作发起方（`admin_api` / `agent:{agent_id}` / `tool_runtime:internal`）
- 注意：`resolve` 操作的审计可选（高频，建议仅在 debug 模式开启）

详细设计见：[credential-vault.md](credential-vault.md)
