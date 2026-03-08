# Tool Runtime TODO

对应需求：`requirements.md#req-5`

## 当前状态

- 已完成条目已清理；历史记录请查看 Git。
- 可运行实现已迁出到同级项目 `../anyagent-apps`；本文件仅保留需求与迁移后的实现证据索引。

## 待处理

### Credential Vault 集成（v1）

- [x] P1 改造 `core.web_fetch`：支持从 `_credentials` 获取认证头（适用于需要鉴权的 URL 访问）（Req: `requirements.md#req-5-9`；Impl: `../anyagent-apps/apps/tool-runtime/src/anyagent_tool_runtime/runtime/executors.py:263`；Module: `tool-runtime`）
  - refs: `../anyagent-apps/tests/acceptance/tool_runtime/acceptance_web_fetch_credentials_smoke.py:1`
- [x] P2 实现 `core.web_search` 内置工具（从 CredentialStore resolve 搜索引擎 API Key）（Req: `requirements.md#req-5-10`；Impl: `../anyagent-apps/apps/tool-runtime/src/anyagent_tool_runtime/runtime/executors.py:338`；Module: `tool-runtime`）
  - refs: `../anyagent-apps/tests/acceptance/tool_runtime/acceptance_web_search_smoke.py:1`
