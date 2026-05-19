# Tool Runtime TODO

对应需求：`requirements.md#req-5`

## 当前状态

- 已完成条目已清理；历史记录请查看 Git。
- 可运行实现已收敛进 Core `anyagent.tool_runtime`；同级项目 `../anyagent-apps` 只保留迁移期兼容入口和验收脚本。

## 待处理

### Credential Vault 集成（v1）

- [x] P1 改造 `core.web_fetch`：支持从 `_credentials` 获取认证头（适用于需要鉴权的 URL 访问）（Req: `requirements.md#req-5-9`；Impl: `packages/anyagent/src/anyagent/tool_runtime/builtin_tools.py:108`；Runtime: `packages/anyagent/src/anyagent/server/runtime.py:330`；Module: `tool-runtime`）
  - refs: apps smoke retained in sibling `../anyagent-apps/tests/acceptance/tool_runtime/`
- [x] P2 实现 `core.web_search` 内置工具（从 CredentialStore resolve 搜索引擎 API Key）（Req: `requirements.md#req-5-10`；Impl: `packages/anyagent/src/anyagent/tool_runtime/builtin_tools.py:163`；Runtime: `packages/anyagent/src/anyagent/server/runtime.py:330`；Module: `tool-runtime`）
  - refs: apps smoke retained in sibling `../anyagent-apps/tests/acceptance/tool_runtime/`
