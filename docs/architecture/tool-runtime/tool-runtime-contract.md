<!--
---
doc_kind: architecture
status: stable
tags: ["tool-runtime", "manifest", "execute", "tool-policy", "federation", "tool-exposure", "tool-search"]
summary: Tool Runtime manifest/execute、registry、tool exposure 分级与按需发现、tool naming、context、idempotency、cancel 与 federation contract。
req: ["requirements.md#req-5", "requirements.md#req-5-1", "requirements.md#req-5-2", "requirements.md#req-5-2-1", "requirements.md#req-5-3", "requirements.md#req-5-8"]
---
-->

# Tool Runtime Contract

Tool Runtime 是工具可见性、工具执行、策略校验、幂等、取消与审计的真源。Agent API 可以计算“希望披露”的工具集合，但最终 `tools[]` 与 execute 权限必须由 Tool Runtime 收口。

## CLI Profile 工具

`AgentToolsSpec.cli` 允许 agent pack 在 `agent.yaml` 里声明受控 CLI profile，并由 Tool Runtime 自动注册成 `kind="command"` 的工具。实现真源见：

- `packages/anyagent/src/anyagent/tool_runtime/cli_profile_spec.py`：profile schema、环境策略与解释器壳黑名单
- `packages/anyagent/src/anyagent/tool_runtime/cli_env.py`：`inherit -> sensitive filter -> exclude -> set -> include_only` 环境求值
- `packages/anyagent/src/anyagent/tool_runtime/cli_profile.py`：tool 定义、manifest 摘要、凭证注入、命令执行与 JSON 输出
- `packages/anyagent/src/anyagent/server/runtime/in_process.py`：manifest 默认把 `tools.cli` profile 作为 agent 可见工具收进候选集合

契约约束：

- profile 名称沿用 tool 命名规则；`app.*`、`core.*`、`sandbox.*`、`<channel>.*` 的 category 仍由 registry 统一推导。
- CLI profile 不需要重复写进 `tools.requested_tool_names`；只要出现在 `tools.cli`，manifest 就会把它当作该 agent 默认可见工具的一部分。
- tool manifest 可附带内部字段 `x-anyagent-cli`，仅暴露 `cwd`、`timeout_ms`、环境策略摘要、`allow_command_prefixes` 与 credential target 名，不暴露密钥或 `credential_id`。
- 运行时 credential 只通过 `_credentials["env:*" / "file:*"]` 注入到子进程；`file:*` 凭证在 profile `cwd` 下临时物化，并在命令退出后清理。
- 上游模型调用前仍会通过 `strip_internal_tool_fields()` 去除 `x-anyagent-cli` / `x-anyagent-kind` 等内部字段。

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

## 内置工具与插件加载

内置工具由 `packages/anyagent/src/anyagent/tool_runtime/builtin_tools.py` 的 `register_builtin_core_tools_sync` 注册，需要显式 allowlist 的 privileged 工具由同文件的 `register_privileged_core_tools_sync` 注册；工具清单以这两个函数为准。内置工具与插件工具走同一个 registry，凭据都通过 `ToolDefinition.credentials` 解析到 handler context 的 `_credentials`，不另开注入通道。

插件以包含 `plugin.json` 的目录形式提供，由 `anyagent.plugins` loader 通过 `ToolRuntimePluginAPI` 注册到 registry。约定：

- 插件根目录来自 `plugins.roots`（环境变量 `PLUGIN_ROOTS`，或 `--plugin-root`）。未设置时，存在 `<workspace>/plugins` 就会扫描它。解析逻辑在 `packages/anyagent/src/anyagent/server/app_builders.py` 与 `packages/anyagent/src/anyagent/tool_runtime/server.py` 的 `_resolve_plugin_roots`。
- 随包插件 `chatwoot` 与 `lifecycle_echo` 默认不加载，在 `.anyagent/anyagent.yaml` 的 `plugins.builtin` 里按名启用。
- 加载失败默认 fail-closed，启动报错；`plugins.fail_open: true` 后记录错误并继续启动。
- 插件被加载不等于对 agent 可见：工具仍需出现在目标 agent 的 `tools.requested_tool_names` 中。`anyagent init` 不生成示例插件。
- 来源追溯：`GET /admin/plugins/catalog`（SDK `client.admin.plugin_catalog()`，CLI `anyagent plugin catalog`）返回 plugin roots、已加载插件、注册的工具、manifest/entrypoint 与 docs/schemas/tests 引用以及加载错误。契约见 [plugin-connector-contract-v1.md](../decisions/plugin-connector-contract-v1.md)。

## Tool Exposure 分级与按需发现

为避免把全部工具 schema 一次性灌进 agent loop 而浪费 context token，每个 `ToolDefinition` 携带 `exposure` 分级，registry 据此决定哪些工具进入初始 manifest、哪些只能按需发现。字段定义见 `packages/anyagent/src/anyagent/tool_runtime/models.py:9`（`ToolExposure = Literal["direct","deferred","hidden"]`）与 `packages/anyagent/src/anyagent/tool_runtime/models.py:29`（`exposure: ToolExposure = "direct"`，默认 direct）。

三种 exposure 语义：

- `direct`：默认值。工具完整 schema 直接进入 manifest，对 agent loop 全量暴露，适合高频/通用工具。
- `deferred`：不进入初始 manifest，agent 初始上下文里看不到其 schema，必须通过 `core.tool_search` 检索后才拿到 schema 再调用。适合数量大、低频或领域专属的工具，用以压缩初始 context。
- `hidden`：既不进 manifest 也不可被 search 命中，仅供内部路由或显式按名调用，对 agent 完全不可发现。

registry 据 exposure 区分两条列举路径（`packages/anyagent/src/anyagent/tool_runtime/registry.py:165`）：

- `list_tools()` 只返回 `exposure == "direct"` 的工具定义，是 manifest 构建的权威来源，`deferred`/`hidden` 不在其中（`packages/anyagent/src/anyagent/tool_runtime/registry.py:165`）。
- `list_all_tools()` 返回全部已注册工具，仅供健康检查与调试，不用于披露（`packages/anyagent/src/anyagent/tool_runtime/registry.py:175`）。

### core.tool_search 与 search_tools 匹配逻辑

`deferred` 工具由内置工具 `core.tool_search` 在运行期按需发现。该工具作为 framework-owned built-in 在 `packages/anyagent/src/anyagent/tool_runtime/builtin_tools.py:130` 注册（handler 见 `packages/anyagent/src/anyagent/tool_runtime/builtin_tools.py:108`），入参 `query` 必填、`limit` 可选（1..20），返回命中工具的 `name`/`description`/`category`/`kind`/`parameters`，让模型据此发起后续 tool call。

`core.tool_search` 委托 registry 的 `search_tools(query, *, limit=10)`（`packages/anyagent/src/anyagent/tool_runtime/registry.py:181`），匹配规则：

- 候选集仅为 `exposure == "deferred"` 的工具，`direct`/`hidden` 永不出现在 search 结果中。
- query 归一化为小写并按空白切成词项；query 为空时直接返回前 `limit` 个候选。
- 每个候选拼接 `name + description + category + kind` 作为 haystack，逐词项计分：命中 `name` 计 3 分，命中其它字段计 1 分；总分 0 的候选被丢弃。
- 按总分降序、同分按 `name` 升序排序，截断到 `limit`。

这套设计让 agent loop 的初始 `tools[]` 只承载 `direct` 工具，`deferred` 工具的 schema 成本被推迟到模型显式检索时才支付，`hidden` 工具则彻底退出可发现面。需求锚点见 `requirements.md#req-5-2` 与 `requirements.md#req-5-2-1`。

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
