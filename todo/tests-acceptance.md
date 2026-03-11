# 测试与验收 TODO

对应需求：`requirements.md#req-9`

## 当前状态

- 应用层验收脚本已迁到同级项目 `../anyagent-apps/tests/acceptance/`；本文件保留系统需求与任务索引。

## 最近完成

- [x] P1 建立 `anyagent` 分层测试策略：明确 `unit / integration / contract / acceptance / live` 的职责、目录建议与补齐顺序，避免把所有回归都堆进 smoke（Req: `requirements.md#req-9`；Impl: `docs/architecture/testing-strategy.md:1`，`docs/architecture/README.md:1`，`tests/README.md:1`；Module: `tests`）
- [x] P1 回补首批 unit tests：为 `session_runtime`、`manifest_cache`、`credential_store`、`exec_handler` 增加模块级快速回归，锁住会话恢复、缓存 key、凭证解析和 UTF-8 截断等核心逻辑（Req: `requirements.md#req-9`；Impl: `tests/unit/agent_runtime/test_session_runtime.py:1`，`tests/unit/server/test_manifest_cache.py:1`，`tests/unit/server/test_credential_store.py:1`，`tests/unit/server/test_exec_handler.py:1`；Module: `tests`）
- [x] P2 回补首批 contract tests：为 SSE block、`response.completed` 提取、`response_id` 归一化和 SDK `stream_typed()` typed 解码增加独立契约回归，减少协议形状回归对大 acceptance 的依赖（Req: `requirements.md#req-9-1`；Impl: `tests/contract/test_sse_protocol_contract.py:1`，`tests/contract/test_events_sdk_contract.py:1`；Module: `tests`）
- [x] P2 回补首批 in-process integration tests：验证 `_handle_sse_block()` 的终态持久化与 `[DONE]` 收敛、以及 external response stream 对 `anyagent.*` 事件的过滤语义（Req: `requirements.md#req-9`；Impl: `tests/integration/server/test_event_pipeline.py:1`；Module: `tests`）

## 待处理

- [ ] P2 扩展 Responses API / SSE / Stage Events contract matrix：补齐更多 payload shape、错误事件与 typed schema fixture，覆盖 OpenAI 兼容面的更多边界（Req: `requirements.md#req-9-1`；Module: `tests`）
- [ ] P2 扩展 in-process integration tests：继续覆盖 `server.app <-> runtime <-> events/store`、manifest cache、session snapshot update 等模块边界（Req: `requirements.md#req-9`；Module: `tests`）
- [ ] P3 补齐安全与负向测试矩阵：覆盖 tool policy、credential scope、secret redaction、畸形 payload 与未授权工具暴露（Req: `requirements.md#req-9`，`requirements.md#req-8`；Module: `tests`）
