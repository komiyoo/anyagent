# tests/contract（协议契约回归）

本目录用于承载 `anyagent` 的协议契约回归，重点保护：

- Responses API / SSE block 形状
- `response.completed` 终态提取与 `response_id` 归一化
- Stage Events typed schema 与 SDK 解码语义

目标：

- 把“协议形状正确”从大 acceptance 脚本中拆出来
- 用最小 fake / fixture 固化对外 contract
- 让协议回归更容易定位和复盘

推荐运行：

```bash
uv run --with pytest --project packages/anyagent pytest tests/contract -q
```
