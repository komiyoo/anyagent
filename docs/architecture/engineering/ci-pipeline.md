<!--
---
doc_kind: architecture
status: stable
tags: ["ci", "quality-gate", "acceptance", "docs"]
summary: anyagent CI 分层质量门：本地 hooks 与 GitHub Actions 离线 gate；目前只提供源码安装，CI 不发布包。
req: ["requirements.md#req-9", "requirements.md#req-7"]
---
-->

# CI 流水线设计（v0 -> v1）

## 目标

- 把“可复现验收”前移到 PR 阶段，减少回归与文档漂移。
- 以离线可执行为基础，不依赖外部模型 API 即可完成核心 gate。

## 分层质量门

### Gate 0：本地 git hooks（必须，提交前）

把 GitHub Actions 里会失败的离线测试前移到本机 `commit` / `push`，避免坏测试进流水线。

首次 clone 后安装：

```bash
bash scripts/install-git-hooks.sh
```

| Hook | 触发 | 命令 |
|---|---|---|
| `pre-commit` | `git commit` | `bash scripts/ci/run_precommit_gate.sh`（docs guardrails + `tests/unit`） |
| `pre-push` | `git push` | `bash scripts/ci/run_prepush_gate.sh`（pytest regressions + offline smokes，对齐 GitHub Actions `offline-quality`） |

约束：

- Agent 与人类默认都走 hooks，不使用 `--no-verify`。
- 紧急跳过（仅用户明确要求）：`ANYAGENT_SKIP_GIT_HOOKS=1`。
- `core.hooksPath` 只写本仓库 local git config，不改全局。
- Cursor 打开本仓或工作区时，`.cursor/hooks/ensure-git-hooks.sh` 会尝试自动安装 hooks。

### Gate 1：结构与文档护栏（必须）

- `python3 scripts/docs/check.py --root . --check-code-refs`
- `python3 scripts/anyagent_progress.py --root .`

目的：

- 防止 Markdown 断链与任务锚点漂移。
- 防止文档中的代码引用在代码移动或删除后失效；示意路径与生成产物登记在 `scripts/docs/code_ref_allowlist.txt`。
- 保持任务文档结构可机械读取。

### Gate 2：离线 SDK / MCP smoke（必须）

建议最小集合：

- `tests/acceptance/sdk/acceptance_anyagent_client_surface_smoke.py`
- `tests/acceptance/sdk/acceptance_command_stage_derivation_smoke.py`
- `tests/acceptance/mcp/acceptance_mcp_federation_smoke.py`

目的：

- 覆盖 Python SDK 协议稳定性、Client surface 与 MCP manifest 合并等关键链路。

### Gate 2.5：正式 pytest regressions（必须）

- `bash scripts/ci/run_pytest_regressions.sh`

目的：

- 把 `unit / contract / integration / targeted server acceptance pytest` 收口成稳定 CI 入口
- 让高频回归不再只依赖 smoke 脚本

### Gate 3：应用层验收（不在本仓）

- 依赖运行中的服务和外部密钥的应用层验收，由各业务仓库针对所依赖的 `anyagent` 版本自行建立门禁。
- 本仓不维护示例应用，也不为业务仓库的验收承担 CI。

## GitHub Actions

仓库 `origin` 是 `https://github.com/komiyoo/anyagent`。Workflow 文件是 `.github/workflows/ci.yml`，名称 `anyagent-ci`，需要保持启用。云效 Flow `4972656` 已停用，不再构建或发布。

| 事件 | Job | 行为 |
|---|---|---|
| `pull_request`，以及 push 到 `main` | `offline-quality` | docs guardrails、协议 schema diff、pytest regressions、offline smokes |
| `workflow_dispatch` | `live-storage-matrix` | 可选的在线存储矩阵，不发布包 |

脚本入口：

- `scripts/ci/run_docs_guardrails.sh`
- `scripts/ci/run_unit_tests.sh`
- `scripts/ci/run_pytest_regressions.sh`
- `scripts/ci/run_offline_smokes.sh`
- `scripts/ci/run_precommit_gate.sh` / `scripts/ci/run_prepush_gate.sh`（本地 git hooks）
- `scripts/ci/run_live_storage_matrix.sh`
- `scripts/ci/build_release_artifacts.sh`（本地构建并检查 wheel/sdist，不上传）

目前只提供源码安装，CI 不构建、不上传任何包：

- 发版就是在 `main` 上提升版本号并打 `vX.Y.Z` tag，使用方从 GitHub 源码安装。
- `sdks/typescript/` 不构建、不发布。Studio 仍通过仓库内 `file:` 依赖使用它。
- `scripts/publish-yunxiao-pypi.sh`、`scripts/notify_release_start.py` 暂时保留，没有 workflow 调用。恢复发布时需要新增 CI job 和仓库 secret，并同步本文与发版清单。

发版步骤见 [docs/release-checklist.md](../../release-checklist.md)。

## 失败处理策略

- Gate 0 失败：阻断本地 commit / push，先修测试再提交。
- Gate 1 失败：直接阻断合并（信息架构/证据链已失真）。
- Gate 2 / 2.5 失败：阻断合并并要求补回归证据。
- Gate 3：由业务仓库自行定义阻断策略，不属于当前仓库 CI 范围。
