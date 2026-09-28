# Scripts

本目录承载仓库级自动化入口。脚本按职责分层，避免把 release、CI、docs guardrail 和本地初始化混在同一个说明里。

## 目录

- `scripts/docs/`：文档系统工具。
  - `index.py` 从 Markdown front matter 与目录结构生成派生 docs index，默认输出到 stdout。
  - `check.py` 检查 Markdown 链接、TODO `Impl:` 证据、docs 可索引性和可选 inline code refs。
  - `pack.py` 按 tags 输出最小文档上下文包。
  - `code_ref_allowlist.txt` 标注 generated / illustrative / cross-repo inline refs，供 `check.py --check-code-refs` 使用。
- `scripts/ci/`：CI/本地质量门入口，详见 [ci/README.md](ci/README.md)。
- `scripts/install-git-hooks.sh`：把本仓 `core.hooksPath` 指到 `.githooks/`，让 commit / push 走与 GitHub Actions `offline-quality` 对齐的本地门禁。
- repo-bound CLI：
  - `anyagent-dev-cli` 运行 `tools/anyagent-dev-cli/` 中的 TypeScript CLI，承载本仓长期复用的开发/发布自动化；开发后用 `npm --prefix tools/anyagent-dev-cli run install:local` 安装到 PATH。
- release：
  - `ci/build_release_artifacts.sh`
  - `publish-yunxiao-pypi.sh`（GitHub Actions `publish-packages` 的上传入口）
  - `notify_release_start.py`
- 本地凭证模板：
  - `credentials.yaml.template`
  - `init-credentials.sh`
- 进度定位：
  - `anyagent_progress.py` 扫描 `todo/*.md`，支持 checkbox 后缩进子项里的 `Impl:` / `Module:` 证据。
- 协议与 SDK：
  - `export_protocol_schema.py` 从 `anyagent.protocol.schema_export` 导出确定性的协议 JSON schema bundle，或用 `--format openapi` 导出同源 OpenAPI 3.1 文档，供多语言 SDK、Studio 和 contract tests 消费；需要在 `packages/anyagent` 项目环境中运行。
  - `protocol_schema_diff.py` 对比两份协议 schema bundle，检测 schema / endpoint 的 breaking change，供本地审查与 CI 护栏复用。

## 常用命令

```bash
bash scripts/install-git-hooks.sh
python3 scripts/anyagent_progress.py --root .
python3 scripts/docs/index.py --root .
python3 scripts/docs/check.py --root . --check-index
python3 scripts/docs/check.py --root . --check-index --check-code-refs
python3 scripts/docs/pack.py --root . --tags sdk
npm --prefix tools/anyagent-dev-cli run install:local
scripts/anyagent-dev-cli version bump 0.4.10 --dry-run
uv run --project packages/anyagent python scripts/export_protocol_schema.py --out build/protocol-schema.json
uv run --project packages/anyagent python scripts/export_protocol_schema.py --format openapi --out build/openapi.json
uv run --project packages/anyagent python scripts/protocol_schema_diff.py --old build/base-protocol-schema.json --new build/protocol-schema.json
npm --prefix sdks/typescript run smoke
bash scripts/ci/run_unit_tests.sh
bash scripts/ci/run_precommit_gate.sh
bash scripts/ci/run_offline_smokes.sh
bash scripts/ci/run_pytest_regressions.sh
bash scripts/ci/run_prepush_gate.sh
bash scripts/ci/build_release_artifacts.sh
```

## 维护规则

- 新增脚本时，在本文件登记用途；CI 质量门脚本还要更新 [ci/README.md](ci/README.md)。
- 文档系统脚本应保持 stdlib-only，方便在最小环境里运行。
- 脚本输出默认适合 agent 读取：稳定、可 grep、少噪声、失败时给出具体路径。
- 高风险 release、发布、镜像同步脚本只登记入口，不在自动验证里默认执行。
