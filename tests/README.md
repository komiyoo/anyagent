# tests（测试脚本索引）

本仓库当前仅保留面向 `packages/anyagent` 的可执行测试/验收脚本（以 acceptance/smoke 为主），避免把测试脚本平铺在 `scripts/` 下导致检索噪音与结构熵增加。

## 目录

- [acceptance/README.md](acceptance/README.md)
  - 面向 SDK 协议解析、Client surface 与 MCP federation 的离线 smoke

## 运行方式

大多数脚本都可以从仓库根目录直接运行（优先 `uv run --project ...`）：

```bash
# 离线 smoke（CI 同款）
bash scripts/ci/run_offline_smokes.sh
```

需要 `agent-api` / `tool-runtime` / storage / OpenAI 兼容面的集成验收，请到同级项目 `../anyagent-apps`。
