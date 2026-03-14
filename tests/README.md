# tests（测试脚本索引）

本仓库当前保留两类测试：

- `tests/unit/`：面向 `packages/anyagent` 的模块级快速回归
- `tests/contract/`：面向 SSE / Responses / Stage Events 的协议契约回归
- `tests/integration/`：面向 in-process 模块边界的集成验证
- `tests/acceptance/`：面向 SDK、MCP、内置 server 主路径的 acceptance/smoke

## 目录

- [acceptance/README.md](acceptance/README.md)
  - 面向 SDK 协议解析、Client surface、MCP federation 与内置 server 的 acceptance/smoke
- [unit/README.md](unit/README.md)
  - 面向纯逻辑与小状态机的快速回归
- [contract/README.md](contract/README.md)
  - 面向协议形状与 typed 解码语义的回归
- [integration/README.md](integration/README.md)
  - 面向 in-process 模块边界的集成验证

## 运行方式

大多数脚本都可以从仓库根目录直接运行（优先 `uv run --project ...`）：

```bash
# unit
uv run --with pytest --project packages/anyagent python -m pytest tests/unit -q

# contract
uv run --with pytest --project packages/anyagent python -m pytest tests/contract -q

# integration
uv run --with pytest --project packages/anyagent python -m pytest tests/integration -q

# formal pytest regressions
bash scripts/ci/run_pytest_regressions.sh

# 离线 smoke（CI 同款）
bash scripts/ci/run_offline_smokes.sh
```

需要 `agent-api` / `tool-runtime` / storage / OpenAI 兼容面的集成验收，请到同级项目 `../anyagent-apps`。
