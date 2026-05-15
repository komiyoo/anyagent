# 测试与验收 TODO

对应需求：`requirements.md#req-9`

## 当前状态

- 应用层验收脚本已迁到同级项目 `../anyagent-apps/tests/acceptance/`；本文件保留系统需求与任务索引。

## 最近完成

- [x] P3 补齐安全与负向测试矩阵：覆盖 tool policy、credential scope、secret redaction、畸形 payload 与未授权工具暴露；并加固 `arguments_json` 为畸形 JSON 字符串时返回结构化 `invalid_arguments`，避免 runtime 抛出非协议化异常（Req: `requirements.md#req-9`，`requirements.md#req-8`；Impl: `packages/anyagent/src/anyagent/server/runtime.py:281`，`tests/unit/server/test_request_validation.py:1`，`tests/unit/server/test_credential_store.py:1`，`tests/unit/protocol/test_stage_events_redaction.py:1`，`tests/integration/server/test_event_pipeline.py:620`，`tests/integration/server/test_event_pipeline.py:668`，`tests/integration/server/test_event_pipeline.py:738`，`tests/integration/server/test_event_pipeline.py:790`；Module: `tests`)
- [x] P3 补齐正式 pytest 回归环境：新增 `scripts/ci/run_pytest_regressions.sh`，并让 GitHub Actions 默认执行 docs guardrails + pytest regressions + offline smokes；同时补一组离线 server acceptance pytest 子集，保证 built-in server 主路径进入正式回归（Req: `requirements.md#req-9`；Impl: `.github/workflows/ci.yml:1`，`scripts/ci/run_pytest_regressions.sh:1`，`tests/acceptance/server/acceptance_builtin_server_smoke.py:201`；Module: `tests`）
- [x] P3 补齐 live storage matrix 入口：新增 `scripts/ci/run_live_storage_matrix.sh`，并在 workflow dispatch 下接 PG/Redis + MySQL/Redis 的 built-in server live 验收（Req: `requirements.md#req-9`；Impl: `.github/workflows/ci.yml:1`，`scripts/ci/run_live_storage_matrix.sh:1`，`tests/acceptance/README.md:1`；Module: `tests`）
- [x] P2 继续扩展 Responses API / SSE / Stage Events contract matrix：补齐 `response.output_text.delta` / `response.output_text.done` / `response.output_item.added` / `response.output_item.done` / `error` / `response.failed` 的 OpenAI SDK typed fixture，并锁住 SDK `stream_typed()` 对 delta、output item、flat error payload 与非数字 SSE id 的解码边界（Req: `requirements.md#req-9-1`；Impl: `tests/contract/test_sse_protocol_contract.py:1`，`tests/contract/test_events_sdk_contract.py:1`；Module: `tests`）
- [x] P2 继续扩展 in-process integration tests：补齐 `/internal/events/list` + `/internal/events/stream` 的 `last_seq` / `limit` / `done` 边界、`/v1/responses/{id}` retrieve/cancel optional payload 语义，以及跨请求 session snapshot 通过 app boundary 回灌 `previous_response_id` / runtime config 的回归（Req: `requirements.md#req-9`；Impl: `tests/integration/server/test_event_pipeline.py:1`；Module: `tests`）
- [x] P2 扩展一批 Responses API / SSE / Stage Events contract matrix：补齐 OpenAI `response.created` / `response.completed` typed fixture 校验、SDK `stream_typed()` 对 created/completed model event payload 的契约回归，覆盖更完整的 OpenAI 兼容事件形状（Req: `requirements.md#req-9-1`；Impl: `tests/contract/test_sse_protocol_contract.py:1`，`tests/contract/test_events_sdk_contract.py:1`；Module: `tests`）
- [x] P2 扩展一批 in-process integration tests：补齐 `server.app <-> runtime <-> events/store` 的 manifest cache 命中、无效请求 short-circuit 不触发 manifest、以及 completed event 通过 `_append_sse_chunk()` 主路径收尾的边界回归（Req: `requirements.md#req-9`；Impl: `tests/integration/server/test_event_pipeline.py:1`；Module: `tests`）
- [x] P1 建立 `anyagent` 分层测试策略：明确 `unit / integration / contract / acceptance / live` 的职责、目录建议与补齐顺序，避免把所有回归都堆进 smoke（Req: `requirements.md#req-9`；Impl: `docs/architecture/testing-strategy.md:1`，`docs/architecture/README.md:1`，`tests/README.md:1`；Module: `tests`）
- [x] P1 回补首批 unit tests：为 `session_runtime`、`manifest_cache`、`credential_store`、`exec_handler` 增加模块级快速回归，锁住会话恢复、缓存 key、凭证解析和 UTF-8 截断等核心逻辑（Req: `requirements.md#req-9`；Impl: `tests/unit/agent_runtime/test_session_runtime.py:1`，`tests/unit/server/test_manifest_cache.py:1`，`tests/unit/server/test_credential_store.py:1`，`tests/unit/server/test_exec_handler.py:1`；Module: `tests`）
- [x] P2 回补首批 contract tests：为 SSE block、`response.completed` 提取、`response_id` 归一化和 SDK `stream_typed()` typed 解码增加独立契约回归，减少协议形状回归对大 acceptance 的依赖（Req: `requirements.md#req-9-1`；Impl: `tests/contract/test_sse_protocol_contract.py:1`，`tests/contract/test_events_sdk_contract.py:1`；Module: `tests`）
- [x] P2 回补首批 in-process integration tests：验证 `_handle_sse_block()` 的终态持久化与 `[DONE]` 收敛、以及 external response stream 对 `anyagent.*` 事件的过滤语义（Req: `requirements.md#req-9`；Impl: `tests/integration/server/test_event_pipeline.py:1`；Module: `tests`）

## 待处理

- 暂无。
