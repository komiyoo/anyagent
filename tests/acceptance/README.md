# tests/acceptance（验收脚本）

本目录当前仅保留面向 `packages/anyagent` 的 acceptance/smoke 脚本，覆盖：

- MCP federation（离线 fake server）
- SDK 强类型事件解析、Client surface、事件回放与安全主路径
- 内置 server 主路径与存储/并发相关验收

## 目录

- [mcp/README.md](mcp/README.md)
- [sdk/README.md](sdk/README.md)

## 推荐运行

```bash
# 离线 smoke（sdk + mcp）
bash scripts/ci/run_offline_smokes.sh
```

应用层集成验收与在线兼容验收已迁到同级项目 `../anyagent-apps/tests/acceptance/`。
