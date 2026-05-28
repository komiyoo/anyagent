<!--
---
doc_kind: architecture
status: stable
tags: ["tool-runtime", "manifest", "execute", "tool-policy", "federation"]
summary: Tool Runtime manifest/execute、registry、tool naming、context、idempotency、cancel 与 federation contract。
req: ["requirements.md#req-5", "requirements.md#req-5-1", "requirements.md#req-5-2", "requirements.md#req-5-3", "requirements.md#req-5-8"]
---
-->

# Tool Runtime Contract

Tool Runtime 是工具可见性、工具执行、策略校验、幂等、取消与审计的真源。Agent API 可以计算“希望披露”的工具集合，但最终 `tools[]` 与 execute 权限必须由 Tool Runtime 收口。

## Tool Execute API

Agent API 通过标准化 execute 接口完成一次 tool call：

- `POST /internal/tools/execute`
- 内部鉴权：mTLS 或签名 JWT / internal key。
- 执行必须支持超时、结构化错误、输出限长、审计字段与幂等。

Tool Runtime 必须对工具执行做权限校验与策略校验，尤其是 channel tools、外部写操作与 `exec`。

## Tool Manifest

- `POST /internal/tools/manifest`
- 输入：`tenant_id?`、`agent_id`、`session_key`、`context`、`enabled_skills?`、`requested_tool_names?`、`requested_tools?`
- 输出：`tools[]`、`toolset_version`、`decisions?`

Agent API 行为：

- 无论外部请求是否携带 `tools[]`，都先向 Tool Runtime 拉取 manifest。
- `requested_tool_names` 来自 AgentSpec、外部 request tool names、skills dependencies 的并集。
- `requested_tools` 只用于审计/调试，不作为 schema 权威。
- Tool Runtime 返回非 MCP 命名空间 tools；MCP tools 由 Agent API 从 Agent Pack `mcp.json` 并行合并。
- 最终 `tools[]` 用于上游模型调用，执行阶段按工具名前缀或保留名路由。

## Manifest 缓存策略

安全优先的短 TTL 缓存：

- 缓存 key 至少包含 `tenant_id`、`agent_id`、`session_key`、`enabled_skills` hash、`requested_tool_names` hash。
- 若 `context` 参与策略判定，必须纳入 key 或裁剪成稳定 `context_cache_key`。
- `execute` 返回 `toolset_version_mismatch` 时刷新 manifest，并对当前 tool call 最多重试一次。
- stale cache 降级必须显式开关，默认关闭，并记录审计与告警。

## Tool Registry 与热更新

v0 启动时加载：

- `core.*` 内置工具。
- `app.*` 业务工具。
- `sandbox.*` 沙箱管理工具。
- `<channel>.*` 平台插件工具。

注册入口要求：

- `registerTool(tool)`：注册工具定义与执行逻辑。
- 可选 `registerNamespaceRoute(prefix, executor_id)`：声明命名空间路由。
- 可选 `listTools()/getTool(name)`：供 manifest 构建、健康检查与调试使用。

约束：

- 内置 `core.*` 也走同一注册路径。
- `tool.name` 与 `tool.category` 必须一致。
- 重复注册同名 tool 必须拒绝。
- 业务方不得注册 `core.*` / `sandbox.*`；平台插件只能注册自身 `<channel>.*`。
- 热更新工具包走控制面 `register/heartbeat`，必须受信任、可审计、可回滚，`toolset_version` 单调递增。

## 工具分类与联邦式 Tool Runtime

工具来源：

- `core`：anyagent 内置工具，例如 `core.web_search`、`core.web_fetch`。
- `app`：业务项目自定义工具，例如 `app.crm.lookup_customer`。
- `sandbox`：未来沙箱管理能力，例如 `sandbox.snapshot`。命令执行不走 `sandbox.*`，统一由保留名 `exec` 表达。
- `channel`：平台工具，例如 `feishu.doc.create`、`discord.message.send`。

路由规则：

- 先精确命中保留名：`exec`、`spawn_agent`、`send_input`、`wait`、`close_agent`、`resume_agent`。
- 再按前缀路由：`core.*`、`app.*`、`sandbox.*`、`<channel>.*`。

联邦形态允许 v0 单进程承载 router + executors，但 sandbox 执行仍必须保留隔离边界。后续可拆成独立 executor 服务。

## 执行语义

必须支持：

- 同步返回最终 `output` string，供 `function_call_output.output` 回灌。
- `timeout_ms` / `deadline_ms`，避免无限占用。
- run abort 时 best-effort cancel。

可选支持：

- `onUpdate` 风格进度事件，作为 anyagent 内部事件流，不强制映射到 OpenAI Responses SSE。

## Tool 命名规范

默认命名：

- 全小写，点号分隔：`<namespace>.<domain>.<action>`。
- 默认字符集：`[a-z0-9_.-]`。
- 发布后不可重命名。
- 必须声明归属类别：`core|app|sandbox|channel`。

保留名例外：

- `exec`
- `spawn_agent`
- `send_input`
- `wait`
- `close_agent`
- `resume_agent`

保留名必须走精确命中路由，不得用前缀模糊匹配。

## Tool Definition

对外工具定义必须能直接落到 OpenAI function tool：

- `type: "function"`
- `function.name`
- `function.description?`
- `function.parameters?`

参数 schema 约束：

- 顶层 `type: "object"`。
- `additionalProperties=false`。
- `required` 显式给出。
- 敏感字段可标记 `x-secret=true`，供内部日志/审计脱敏使用。

## internal/tools/execute 字段契约

### Request Agent API -> Tool Runtime Router

```json
{
  "tenant_id": "t_default",
  "agent_id": "main",
  "session_key": "feishu:oc_123:om_456",
  "response_id": "resp_...",
  "tool_call_id": "call_...",
  "tool_name": "feishu.doc.create",
  "arguments_json": "{\"title\":\"Spec\",\"folder_id\":\"fld...\"}",
  "deadline_ms": 30000,
  "context": { "trace": { "trace_id": "..." }, "channel": { "provider": "feishu" } }
}
```

关键字段：

- `agent_id` 与 `session_key` 共同决定 `session_partition_key`。
- `tool_call_id` 来自模型 function call，用于幂等与回放。
- `arguments_json` 可以是 JSON string 或 object；Tool Runtime 必须解析成 object 后校验。
- `deadline_ms` 是剩余预算，不是软建议。
- `context` 是标准化上下文。

### Response Tool Runtime -> Agent API

```json
{
  "status": "completed",
  "output": "{\"doc_id\":\"doccn...\"}",
  "meta": {
    "duration_ms": 532,
    "output_truncated": false,
    "audit_ref": "aud_..."
  }
}
```

错误响应：

```json
{
  "status": "error",
  "error": {
    "type": "tool_input_error",
    "code": "missing_required_field",
    "message": "folder_id required",
    "retryable": false
  },
  "meta": { "duration_ms": 12, "audit_ref": "aud_..." }
}
```

约束：

- 错误必须结构化。
- `output` 必须限长；超限设置 `meta.output_truncated=true`。
- 大结果或二进制结果走对象存储并在 `output` 返回引用 JSON。

## context 标准结构

```json
{
  "trace": { "trace_id": "tr_...", "span_id": "sp_..." },
  "requester": { "id": "u_123", "display_name": "Alice", "is_owner": false },
  "channel": {
    "provider": "feishu",
    "account_id": "acc_default",
    "chat_id": "oc_123",
    "thread_id": "om_456",
    "message_id": "omsg_789"
  },
  "auth_ref": { "kind": "secret_ref", "ref": "sec_feishu_acc_default" },
  "policy": { "allow_tools": ["feishu.*", "core.*"], "deny_tools": ["exec"] },
  "locale": { "timezone": "Asia/Shanghai", "lang": "zh-CN" }
}
```

规则：

- `auth_ref` 必须是引用，禁止把 token 放入 context。
- `policy` 来源必须是服务端配置；调用方传入的 `metadata.context.policy` 默认忽略。
- 平台扩展字段放在 `channel.ext`。

## 幂等与去重

建议幂等键：`idempotency_key = "{response_id}:{tool_call_id}"`。

重复请求：

- 已完成：返回完全相同结果。
- 执行中：返回 retryable error 或明确 `in_progress` 语义。

## 取消语义

- `POST /internal/tools/cancel`
- body：`{ tenant_id?, agent_id, session_key, response_id, tool_call_id }`
- Tool Runtime best-effort 停止执行，尤其是 sandbox exec。
- 取消不是强一致；允许返回 `not_found` 或 `already_completed`。

Agent API 在 run abort 后优先发送 tool cancel，再停止继续推理。
