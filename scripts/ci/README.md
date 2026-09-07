# CI Scripts

本目录用于承载可复用的 CI 执行脚本，避免把所有命令堆在 workflow yaml 里。

当前脚本：

1. `run_docs_guardrails.sh`：文档护栏与进度可读性检查，适合 docs / roadmap / TODO 变更后的最小质量门。
2. `run_protocol_schema_diff.sh`：导出当前 protocol schema bundle，并与 base branch 的 generated bundle 比较，拦截字段删除、required 新增、类型/枚举收窄与 endpoint 破坏性变更。
3. `run_offline_smokes.sh`：离线 smoke 集合（不依赖上游模型 API），当前覆盖 SDK client surface 与 MCP federation。
4. `run_unit_tests.sh`：`tests/unit` 快速回归，供 pre-commit 与 pytest regressions 复用。
5. `run_pytest_regressions.sh`：正式 pytest 回归集合，当前覆盖 `unit`、`contract`、`integration` 与一组离线 server acceptance pytest。
6. `run_precommit_gate.sh`：本地 `git commit` 门禁，跑 docs guardrails + unit tests。
7. `run_prepush_gate.sh`：本地 `git push` 门禁，对齐 Yunxiao SDK build 的测试段（pytest regressions + offline smokes）。
8. `run_live_storage_matrix.sh`：live storage matrix 入口，当前覆盖 PG/Redis 与 MySQL/Redis 的 built-in server 验收。
9. `build_release_artifacts.sh`：发布构建入口，只构建 Python wheel/sdist、执行 `twine check` 和最小 wheel metadata smoke；全量 pytest 应在 CI gate 中完成，不放在发版上传前重复执行。

本地 git hooks：

- 安装：`bash scripts/install-git-hooks.sh`（把 `core.hooksPath` 指到 `.githooks/`）
- 设计说明见 [docs/architecture/engineering/ci-pipeline.md](../../docs/architecture/engineering/ci-pipeline.md)

补充：

- `python3 scripts/docs/check.py --root .`：默认检查 Markdown link 与 TODO `Impl:` 证据。
- `python3 scripts/docs/check.py --root . --check-code-refs`：额外检查反引号里的 `path` / `path:line` 明文引用，并读取 `scripts/docs/code_ref_allowlist.txt` 跳过 generated / illustrative / cross-repo refs，适合做迁移清理或大规模重构后的断链扫描。
- 脚本总览见 [../README.md](../README.md)。
