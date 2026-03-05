# tests（测试脚本索引）

本目录用于放置**可执行的测试/验收脚本**（以 acceptance/smoke 为主），避免把测试脚本平铺在 `scripts/` 下导致检索噪音与结构熵增加。

## 目录

- [acceptance/README.md](acceptance/README.md)
  - 面向协议/存储/会话/MCP 等关键链路的离线 smoke，以及少量可选的在线（依赖 OpenAI SDK/外部服务）验收脚本

## 运行方式

大多数脚本都可以从仓库根目录直接运行（优先 `uv run --project ...`）：

```bash
# 离线 smoke（CI 同款）
bash scripts/ci/run_offline_smokes.sh
```

更详细的验收说明见 `docs/acceptance/*`。

