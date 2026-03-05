<!--
---
doc_kind: architecture
status: stable
tags: ["ci", "quality-gate", "acceptance", "docs"]
summary: anyagent CI 分层质量门设计：结构检查、协议/离线 smoke、可选在线验收。
req: ["requirements.md#req-9", "requirements.md#req-7"]
---
-->

# CI 流水线设计（v0 -> v1）

## 目标

- 把“可复现验收”前移到 PR 阶段，减少回归与文档漂移。
- 以离线可执行为基础，不依赖外部模型 API 即可完成核心 gate。

## 分层质量门

### Gate 1：结构与文档护栏（必须）

- `python3 scripts/docs/check.py --root .`
- `python3 scripts/anyagent_progress.py --root .`

目的：

- 防止 Markdown 断链、TODO 证据漂移。
- 保持 TODO 进度可机械读取。

### Gate 2：离线协议与存储 smoke（必须）

建议最小集合：

- `tests/acceptance/sdk/acceptance_command_stage_derivation_smoke.py`
- `tests/acceptance/mcp/acceptance_mcp_federation_smoke.py`
- `tests/acceptance/storage/acceptance_rollout_replay_smoke.py`
- `tests/acceptance/storage/acceptance_rollout_rotation_smoke.py`
- `tests/acceptance/storage/acceptance_rollout_storage_consistency_smoke.py`
- `tests/acceptance/agent_api/acceptance_session_resume_smoke.py`

目的：

- 覆盖协议稳定性、MCP 合并、rollout/replay、session runtime 绑定等关键链路。

### Gate 3：在线兼容验收（可选，受密钥/环境约束）

- `tests/acceptance/agent_api/acceptance_responses_smoke.py`
- `tests/acceptance/openai/acceptance_openai_sdk_smoke.py`

说明：

- 该层依赖 `OPENAI_API_KEY` 与运行中的服务，默认不阻塞普通 PR。
- 可用于 nightly 或 release 分支门禁。

## GitHub Actions 编排（本次落地）

- Workflow：`.github/workflows/ci.yml`
- 脚本分层：
  - `scripts/ci/run_docs_guardrails.sh`
  - `scripts/ci/run_offline_smokes.sh`

## 失败处理策略

- Gate 1 失败：直接阻断合并（信息架构/证据链已失真）。
- Gate 2 失败：阻断合并并要求补回归证据。
- Gate 3 失败：标记为 `warning` 或仅在 release 分支阻断（按环境成熟度逐步收紧）。
