# tests/integration（模块边界集成）

本目录用于承载 `anyagent` 的 in-process integration tests，重点验证：

- `server.app`、`runtime`、`events/store` 等模块边界
- 不依赖真实外部服务，但需要真实对象协作的链路
- 比 acceptance 更快、比 unit 更接近真实主路径

推荐运行：

```bash
uv run --with pytest --project packages/anyagent python -m pytest tests/integration -q
```
