# Backlog TODO

对应需求：待分流

## 当前状态

- [x] 本地开发启动 DX：新增 `anyagent dev` 默认挂载 Studio、自动使用本地 dev key，并让 `serve/dev` 在启动前打印 API、OpenAPI、Studio、key 状态和 agent 概览。
  - Req: `requirements.md#0-2-交付形态配置即服务`
  - Impl: `packages/anyagent/src/anyagent/cli.py`
  - Module: `sdk-cli/dev`
  - Tests: `tests/unit/test_cli_workspace_commands.py`
- [x] Workspace agent 发现：新增 `anyagent agent list --workspace ...`，支持人读输出与 JSON 输出，避免开发者猜 admin/internal endpoint。
  - Req: `requirements.md#req-2-1`
  - Impl: `packages/anyagent/src/anyagent/cli.py`
  - Module: `sdk-cli/agent-catalog`
  - Docs: `README.md`
  - Tests: `tests/unit/test_cli_workspace_commands.py`
