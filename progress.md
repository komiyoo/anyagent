# Progress

## 2026-03-09
- 初始化文件化计划。
- 已阅读 `README.md`、`docs/architecture/roadmap.md`，并运行 `scripts/anyagent_progress.py --root .`。
- 已核对 Stage Events / Client SDK 文档与实现差异。
- 已按文档补齐 Tool Runtime `audit_ref` 生成与最小结构化审计日志。
- 已按文档补齐 `ToolContext.trace.trace_id` 到 `anyagent.tool.*` / `anyagent.command.*` Stage Events 的透传。
- 已按文档补齐 replay 末尾 `[DONE]` 的持久化：Event Store 真实保存 `[DONE]`，`/internal/events/stream` 与外部 replay 复用真实 seq，不再伪造 `next_last_seq + 1`。
- 已按文档补齐 Tool Runtime 凭证注入：`ToolCredentialSpec` 会在执行前 resolve，注入 handler `context["_credentials"]`，required 凭证缺失返回 `credential_not_found`。
- 已按文档补齐 exec 输出截断：支持 `sandbox.resources.output_max_bytes`/`resource_limits.output_max_bytes`，截断 stdout/stderr，并把 `output_truncated` 贯通到 `ExecuteMeta` 与审计日志。
- 已按文档补齐凭证 set/delete 审计：记录结构化 `credential_audit` 日志，包含 `audit_ref` 与 `credential_id`，不泄漏 secret value。
- 已按文档补齐凭证 kind 校验：`AuthRef.kind` 现在必须与 `credential.kind` / `ToolCredentialSpec.ref_kind` 一致，错 kind 不再命中凭证。
- 验证结果：`bash scripts/ci/run_offline_smokes.sh` 通过，错 `kind` 的凭证注入 smoke 断言已纳入 `acceptance_tool_credential_injection_smoke.py`。
