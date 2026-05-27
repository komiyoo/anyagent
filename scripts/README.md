# Scripts

本目录承载仓库级自动化入口。脚本按职责分层，避免把 release、CI、docs guardrail 和本地初始化混在同一个说明里。

## 目录

- `scripts/docs/`：文档系统工具。
  - `index.py` 从 Markdown front matter 与目录结构生成派生 docs index，默认输出到 stdout。
  - `check.py` 检查 Markdown 链接、TODO `Impl:` 证据、docs 可索引性和可选 inline code refs。
  - `pack.py` 按 tags 输出最小文档上下文包。
  - `code_ref_allowlist.txt` 标注 generated / illustrative / cross-repo inline refs，供 `check.py --check-code-refs` 使用。
- `scripts/ci/`：CI/本地质量门入口，详见 [ci/README.md](ci/README.md)。
- release / 镜像同步：
  - `publish-yunxiao-pypi.sh`
  - `publish-yunxiao-npm.sh`
  - `notify_release_start.py`
  - `mirror-codeup-to-github.sh`
- 本地凭证模板：
  - `credentials.yaml.template`
  - `init-credentials.sh`
- 进度定位：
  - `anyagent_progress.py` 扫描 `todo/*.md`，支持 checkbox 后缩进子项里的 `Impl:` / `Module:` 证据。
- 协议与 SDK：
  - `export_protocol_schema.py` 从 `anyagent.protocol.schema_export` 导出确定性的协议 JSON schema bundle，或用 `--format openapi` 导出同源 OpenAPI 3.1 文档，供多语言 SDK、Studio 和 contract tests 消费；需要在 `packages/anyagent` 项目环境中运行。

## 常用命令

```bash
python3 scripts/anyagent_progress.py --root .
python3 scripts/docs/index.py --root .
python3 scripts/docs/check.py --root . --check-index
python3 scripts/docs/check.py --root . --check-index --check-code-refs
python3 scripts/docs/pack.py --root . --tags sdk
uv run --project packages/anyagent python scripts/export_protocol_schema.py --out build/protocol-schema.json
uv run --project packages/anyagent python scripts/export_protocol_schema.py --format openapi --out build/openapi.json
npm --prefix sdks/typescript run smoke
bash scripts/ci/run_offline_smokes.sh
bash scripts/ci/run_pytest_regressions.sh
```

## 维护规则

- 新增脚本时，在本文件登记用途；CI 质量门脚本还要更新 [ci/README.md](ci/README.md)。
- 文档系统脚本应保持 stdlib-only，方便在最小环境里运行。
- 脚本输出默认适合 agent 读取：稳定、可 grep、少噪声、失败时给出具体路径。
- 高风险 release、发布、镜像同步脚本只登记入口，不在自动验证里默认执行。
