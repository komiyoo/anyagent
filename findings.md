# Findings

## 2026-03-09
- `docs/architecture/roadmap.md` 明确 Phase 2 要交付 `client.events.stream_typed()`、`client.events.list()`、`last_seq` 断线续传。
- `requirements.md` 多处将 Stage Events 和 typed event stream 定义为 SDK 核心能力。
- 当前 `todo/sdk.md` 已清空，不能作为未完成功能的唯一判断来源。
- 代码核对结果：`client.events.stream_typed()`、`/internal/events/stream`、`StageEvent` union 已基本落地。
- 已修复偏差 1：`docs/security/audit-logging.md` 与 `docs/architecture/agent-api-client-stage-events.md` 要求 tool result / audit log 带稳定 `audit_ref`；此前 `packages/anyagent/src/anyagent/server/runtime.py` 未实际赋值。现已补齐稳定生成、缓存复用与结构化日志。
- 已修复偏差 2：`docs/architecture/agent-api-client-stage-events.md` 规定 Stage Events 通用字段应包含 `trace_id`（若有）；此前 `packages/anyagent/src/anyagent/agent_runtime/tool_loop.py` 生成的 `anyagent.tool.*` / `anyagent.command.*` 事件未透传 `ToolContext.trace.trace_id`。现已补齐从 ToolContext 到 Stage Events 的 `trace_id` 贯通。
- 已修复偏差 3：`docs/architecture/agent-api-client-stage-events.md` 规定 `/internal/events/stream` 返回“持久化的 SSE blocks，按 seq 单调递增，最终以 [DONE] 结束”，时序图还明确 `append([DONE])`。此前 `packages/anyagent/src/anyagent/server/app.py` 没有把 `[DONE]` 写入 Event Store，而是在 replay 路由里伪造了一个 `done_id = next_last_seq + 1`。现已改为持久化 `[DONE]`，并让 internal/external replay 都复用真实存储 seq。
- 已修复偏差 4：`docs/security/credential-vault.md` 与 `docs/security/security-threat-model.md` 要求 Tool Runtime 在 handler 执行前按 `ToolCredentialSpec` 自动 resolve 凭证，并仅通过 `context["_credentials"]` 注入给 handler。此前 `packages/anyagent/src/anyagent/server/runtime.py` 完全未接入 `credential_store`，`ToolDefinition.credentials` 也未参与执行路径。现已补齐 `credential_store → execute() → _credentials` 的注入链路，并在缺失 required 凭证时返回 `credential_not_found`。
- 已修复偏差 5：`docs/security/sandbox-security.md` 要求 `exec` 调用记录 `output_truncated`，且 agent.yaml 示例使用 `sandbox.resources.output_max_bytes`。此前协议层没有 `output_max_bytes` 字段，也不识别 `resources` alias；`exec` 路径从不截断输出，`ExecuteMeta.output_truncated` 始终为 `False`。现已补齐 `SandboxPolicy.resources -> resource_limits` alias、`ResourceLimits.output_max_bytes` 字段、`exec` stdout/stderr 截断与 `ExecuteMeta.output_truncated` 贯通。
- 已修复偏差 6：`docs/security/credential-vault.md` 与 `docs/security/security-threat-model.md` 要求凭证 `set/delete` 记录审计事件，且日志中只保留 `credential_id` 等引用、不得泄漏 `value`。此前 `packages/anyagent/src/anyagent/server/security/credential_store.py` 对 set/delete 完全无审计。现已补齐最小结构化审计日志，包含 `audit_ref` / `operation` / `credential_id` / scope 信息，且不记录明文值。
- 已修复偏差 7：`docs/security/credential-vault.md` 明确 `AuthRef.kind` 应匹配 `credential.kind`。此前 `packages/anyagent/src/anyagent/server/security/credential_store.py` 在 `resolve()` 时只看 `credential_id` 不看 `kind`，而 `packages/anyagent/src/anyagent/server/runtime.py` 还会直接用 `ToolCredentialSpec.ref_kind` 覆盖 caller 的 `auth_ref.kind`，导致错误 kind 也能命中凭证。现已在 store 与 runtime 两侧都补上 kind 校验，错 kind 会返回 `credential_not_found`。
- `docs/security/tool-policy.md` 这条契约已符合实现：`packages/anyagent/src/anyagent/server/app.py` 的 `_sanitize_caller_tool_context()` 会丢弃 caller 注入的 `policy`，只保留服务端生成/合并的策略。
