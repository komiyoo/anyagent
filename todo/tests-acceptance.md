# 测试与验收 TODO

对应需求：`requirements.md#req-9`

## 目标

- 把“Responses API 兼容性”与“Gateway 端到端”验收落成可重复的测试清单与自动化用例。

## 里程碑（Milestones）

- M1：最小验收用例可跑通（手动 + 自动）
- M2：关键路径自动化（CI 可跑）
- M3：回归与兼容性基线稳定

## 任务（Tasks）

- [x] P0 列出 Responses API 兼容性验收清单与用例（Req: `requirements.md#req-9-1`；Impl: `docs/acceptance/acceptance-responses-api.md:1`；Module: `docs`）
- [x] P0 列出 Gateway 端到端验收清单与用例（Req: `requirements.md#req-9-2`；Impl: `docs/acceptance/acceptance-gateway-e2e.md:1`；Module: `docs`）
- [x] P1 把验收用例沉淀为自动化测试（逐步覆盖）（Req: `requirements.md#req-9`；Impl: `tests/acceptance/agent_api/acceptance_responses_smoke.py:1`；Module: `tests/acceptance/agent_api`）
- [x] P0 新增 `rollout.jsonl` 持久化验收：`STORAGE_MODE=none` 与外部存储模式下事件链路一致（Req: `requirements.md#req-3-1`，`requirements.md#req-7`，`requirements.md#req-9`；Impl: `tests/acceptance/storage/acceptance_rollout_storage_consistency_smoke.py:1`, `apps/agent-api/src/anyagent_agent_api/storage/runtime.py:210`；Module: `tests/acceptance/storage`）
- [x] P1 新增 replay 验收：按 `session_partition_key + response_id + last_seq` 回放，验证 turn/item/tool_call 关联可重建（Req: `requirements.md#req-4-4`，`requirements.md#req-7`，`requirements.md#req-9`；Impl: `tests/acceptance/storage/acceptance_rollout_replay_smoke.py:1`；Module: `tests/acceptance/storage`）
- [x] P1 新增写入门控验收：重复请求/重复 tool call 在写前被判重拦截，不产生重复 rollout 事件（Req: `requirements.md#req-5-11`，`requirements.md#req-7`，`requirements.md#req-9`；Impl: `tests/acceptance/storage/acceptance_rollout_replay_smoke.py:1`；Module: `tests/acceptance/storage`）
- [x] P1 新增 rollout 轮转验收：`rollout*.jsonl` 归档文件可被 replay 覆盖读取，且轮转后事件游标连续（Req: `requirements.md#req-3-1`，`requirements.md#req-7`，`requirements.md#req-9`；Impl: `tests/acceptance/storage/acceptance_rollout_rotation_smoke.py:1`, `apps/agent-api/src/anyagent_agent_api/storage/rollout_replay.py:86`；Module: `tests/acceptance/storage`）
- [x] P0 新增 Session Resume 验收：同一 `session_partition_key` 两次请求，第二次仅发送增量输入仍能承接上下文（覆盖外部存储与 `STORAGE_MODE=none`）（Req: `requirements.md#req-4-6-1`，`requirements.md#req-7`，`requirements.md#req-9-1`；Impl: `tests/acceptance/agent_api/acceptance_session_resume_smoke.py:145`；Module: `tests/acceptance/agent_api`）
- [x] P0 新增会话参数绑定验收：`model/temperature/top_p/frequency_penalty/presence_penalty/reasoning` 默认复用，显式传参时字段级 merge 更新（Req: `requirements.md#req-4-6-2`，`requirements.md#req-9-1`；Impl: `tests/acceptance/agent_api/acceptance_session_resume_smoke.py:105`；Module: `tests/acceptance/agent_api`）
- [x] P1 新增工具回合参数一致性验收：`previous_response_id` 回合继承同一 `effective_runtime_config`（Req: `requirements.md#req-4-6-2`，`requirements.md#req-9-1`；Impl: `tests/acceptance/agent_api/acceptance_session_resume_smoke.py:132`；Module: `tests/acceptance/agent_api`）
- [x] P1 新增 stage events 命令派生验收：command-like tool 的 `anyagent.command.*` 事件可被强类型解析，且命令预览默认脱敏（Req: `requirements.md#req-7`，`requirements.md#req-9`；Impl: `tests/acceptance/sdk/acceptance_command_stage_derivation_smoke.py:1`；Module: `tests/acceptance/sdk`）
- [x] P1 新增 MCP Federation 验收：验证 `mcp.json` 加载、manifest 合并与 `mcp.` 路由（离线 fake server）（Req: `requirements.md#req-4-5`，`requirements.md#req-5-2`，`requirements.md#req-12-4`；Impl: `tests/acceptance/mcp/acceptance_mcp_federation_smoke.py:1`；Module: `tests/acceptance/mcp`）
- [x] P1 新增可选 endpoint 验收：`GET /v1/responses/{id}` + `POST /v1/responses/{id}/cancel` 的离线闭环（Req: `requirements.md#req-4-1`；Impl: `tests/acceptance/agent_api/acceptance_optional_responses_endpoints_smoke.py:1`；Module: `tests/acceptance/agent_api`）
- [x] P1 Demo：提供默认配置示例（`.env.example` + workspace 模板），上手时可直接替换关键字段（Req: `requirements.md#req-9-1`；Impl: `apps/agent-api/.env.example:1`；Module: `demo/acceptance`）
  - refs: `apps/tool-runtime/.env.example:1`，`examples/demo-workspace/.agents/agents/main/agent.yaml:1`，`docs/acceptance/acceptance-demo-customization.md:1`
- [x] P0 设计并落地分层 CI 质量门（docs guardrails + offline smoke + optional online smoke）（Req: `requirements.md#req-9`；Impl: `docs/architecture/engineering/ci-pipeline.md:1`；Module: `architecture/ci`）
- [x] P1 实现 CI workflow 与脚本分层（GitHub Actions + `scripts/ci/*`）（Req: `requirements.md#req-9`；Impl: `.github/workflows/ci.yml:1`；Module: `ci`）
  - refs: `scripts/ci/run_docs_guardrails.sh:1`，`scripts/ci/run_offline_smokes.sh:1`
