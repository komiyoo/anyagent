# tests/unit（模块级快速回归）

本目录用于承载 `packages/anyagent` 的 unit tests，目标是：

- 快速验证纯逻辑与小状态机
- 在 acceptance 之前尽早暴露回归
- 让失败可以直接定位到模块，而不是只能从大闭环脚本倒推

当前优先覆盖：

- `agent_runtime/session_runtime.py`
- `agent_api_client.py` 中的本地 explain / example helpers
- `server/manifest_cache.py`
- `server/security/credential_store.py`
- `server/sandbox/exec_handler.py`

推荐运行：

```bash
uv run --with pytest --project packages/anyagent python -m pytest tests/unit -q
```

约定：

- 尽量不依赖外部服务
- 优先测纯函数、归一化逻辑、边界值和最小状态转换
- 复杂链路仍由 `tests/acceptance/` 承担闭环证明
