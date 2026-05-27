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

- 防止 Markdown 断链与任务锚点漂移。
- 保持任务文档结构可机械读取。

### Gate 2：离线 SDK / MCP smoke（必须）

建议最小集合：

- `tests/acceptance/sdk/acceptance_anyagent_client_surface_smoke.py`
- `tests/acceptance/sdk/acceptance_command_stage_derivation_smoke.py`
- `tests/acceptance/mcp/acceptance_mcp_federation_smoke.py`
- `npm --prefix sdks/typescript run smoke`

目的：

- 覆盖 Python / TypeScript SDK 协议稳定性、Client surface 与 MCP manifest 合并等关键链路。

### Gate 2.5：正式 pytest regressions（必须）

- `bash scripts/ci/run_pytest_regressions.sh`

目的：

- 把 `unit / contract / integration / targeted server acceptance pytest` 收口成稳定 CI 入口
- 让高频回归不再只依赖 smoke 脚本

### Gate 3：应用层兼容验收（迁出到场景项目）

- 同级项目：`../anyagent-apps`
- 文档入口：`../anyagent-apps/docs/acceptance/`
- 脚本入口：`../anyagent-apps/tests/acceptance/`

说明：

- 该层依赖运行中的 `agent-api` / `tool-runtime` 服务以及外部密钥，已从当前 SDK 仓库剥离。
- 如需为场景项目单独建立 CI，可在对应仓库内再配置 nightly / release 级门禁。

## GitHub Actions 编排（本次落地）

- Workflow：`.github/workflows/ci.yml`
- 脚本分层：
  - `scripts/ci/run_docs_guardrails.sh`
  - `scripts/ci/run_pytest_regressions.sh`
  - `scripts/ci/run_offline_smokes.sh`
  - `scripts/ci/run_live_storage_matrix.sh`（`workflow_dispatch` 手动触发）

## 失败处理策略

- Gate 1 失败：直接阻断合并（信息架构/证据链已失真）。
- Gate 2 / 2.5 失败：阻断合并并要求补回归证据。
- Gate 3：由场景项目自行定义阻断策略，不再属于当前仓库 CI 范围。
