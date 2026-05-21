# Agent API TODO

对应需求：`requirements.md#req-4`

## 当前状态

- 已完成条目已清理；历史记录请查看 Git。
- 当前仓库已回补最小内置 `anyagent serve` 主路径（FastAPI app + in-proc runtime + `/v1/responses` 基础闭环）；应用层扩展能力仍可在同级项目 `../anyagent-apps` 继续演进。

## 收尾状态

### 最近完成

- [x] 分布式 Agent API 与 built-in server 已把主编排、manifest cache / requested tool names、request validation、persisted stream/nonstream append_event / terminal finalizer 等共享语义收敛到 Core helper；`anyagent-apps/apps/agent-api` 已删除，业务仓只保留消费侧验收（Req: `requirements.md#req-4`；Impl: `packages/anyagent/src/anyagent/server/app.py:1`，`packages/anyagent/src/anyagent/server/distributed_app.py:1`，`packages/anyagent/src/anyagent/server/distributed_responses.py:1`，`packages/anyagent/src/anyagent/server/request_validation.py:1`；Module: `agent-api`）
- [x] 本轮 targeted acceptance 已覆盖 current convergence batch：Core direct targeted validations，以及 apps `acceptance_manifest_cache_smoke`、`acceptance_request_validation_smoke`、`acceptance_session_resume_smoke`（Req: `requirements.md#req-4`，`requirements.md#req-9`；Impl: `tests/unit/server/test_manifest_cache.py:1`，`tests/unit/server/test_request_validation.py:1`，`tests/unit/server/test_finalization.py:1`，`tests/unit/server/test_streaming.py:1`；Module: `agent-api`）

### 待处理

- 当前没有未完成事项。
