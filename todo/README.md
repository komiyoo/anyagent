# TODO（按模块拆分）

本目录用 Markdown checkbox 维护 anyagent 的工程任务，每条任务追溯到 `requirements.md` 的稳定锚点。

## 约定

### 1) 单一真源

- 需求真源：`requirements.md`
- 任务真源：`todo/*.md`
- 每条任务附带 `Req: requirements.md#req-*`

### 2) 任务条目格式

- `- [ ] P0 <任务>（Req: requirements.md#req-...）`
- 完成时：`- [x] P0 <任务>（Req: ...；Impl: <path:line>；Module: <module>）`

### 3) 分流规则

- 新想法先落 `todo/backlog.md`
- 确定归属模块后迁移到 `todo/<module>.md`

## 模块文件

- `todo/backlog.md`：未分配事项
- `todo/agent-api.md`：Responses API 兼容 + 内置 Server（`requirements.md#req-4`）
- `todo/tool-runtime.md`：Tool Runtime 协议与执行（`requirements.md#req-5`）
- `todo/storage.md`：存储层（`requirements.md#req-3-1`）
- `todo/gateway.md`：平台接入（`requirements.md#req-6`）
- `todo/concurrency-reliability.md`：并发与可靠性（`requirements.md#req-7`）
- `todo/security-compliance.md`：安全与合规，含 Credential Vault（`requirements.md#req-8`）
- `todo/tests-acceptance.md`：测试与验收（`requirements.md#req-9`）
- `todo/skills-disclosure.md`：Skills 加载与动态披露（`requirements.md#req-12`）
- `todo/multi-agent.md`：Multi-Agent（`requirements.md#req-13`）
- `todo/sdk.md`：Client SDK + CLI（`requirements.md#req-4`）
