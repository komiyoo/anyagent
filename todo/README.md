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

- 新想法如果能立即归属，直接落到对应 `todo/<module>.md`。
- 如果没有现成模块文件，先用 `_template.md` 新建一个聚焦的模块 TODO；不要保留没有待办事项的空模块文件。

## 活跃模块文件

按 Roadmap Phase 分类（详见 [`docs/architecture/overview/roadmap.md`](../docs/architecture/overview/roadmap.md)）：

**Phase 1 — Protocol & SDK Hardening**

- `todo/protocol.md`：Protocol / Schema bundle 版本化与 diff 工具（`requirements.md#req-7`）
- `todo/sdk.md`：SDK 框架自身（Python + TypeScript + conformance fixtures）（`requirements.md#req-4`）

**Phase 1.5 — Agentic Ecosystem Hardening**

- `todo/tool-runtime.md`：Tool Deferred Loading、Tool Search、Plugin Manifest 统一、MCP filter（`requirements.md#req-5-2`、`requirements.md#req-5-2-1`、`requirements.md#req-6`）
- `todo/server-runtime.md`：Skill 注入管道、配置层级 merge、MCP 生命周期事件、AGENTS.md 层级遍历（`requirements.md#req-5`）
- `todo/sdk.md`：SDK Skill Injection / Tool Discovery / 配置层级感知（`requirements.md#req-4`）

**Phase 1.8 — Internal Productivity（内部生产力提升）**

- `todo/multi-agent.md`：Sub-Agent 最小可用版（`task()` tool 模式）（`requirements.md#req-13`）
- `todo/server-runtime.md`：上下文压缩、循环检测、DeerFlow Skills 嵌入（`requirements.md#req-5`）

**Phase 2 — Production Runtime Hardening**

- `todo/server-runtime.md`：跨节点 Run 调度、lock、observability envelope（`requirements.md#req-5`）
- `todo/storage.md`：分布式存储 replay 与一致性（`requirements.md#req-3-1`）
- `todo/tool-runtime.md`：Tool Runtime contract 与 plugin/connector（`requirements.md#req-6`）
- `todo/sandbox.md`：第二 sandbox backend（`requirements.md#req-12`）

**Phase 3 — Security & Credential v2**

- `todo/security-compliance.md`：Credential v2（DB / Vault / session scope / 轮转 / 审计）（`requirements.md#req-8`）

**Phase 4 — Ecosystem & Multi-Runtime**

- `todo/multi-runtime.md`：reference conformance suite 与第二 server runtime（`requirements.md#req-5`、`requirements.md#req-7`）
- `todo/multi-agent.md`：parent/child/root run、quota、replay 语义验收（`requirements.md#req-13`）

**Studio — 独立产品迭代线**

- `todo/studio.md`：Studio 控制台的架构治理、Chat 体验、表单反馈、Eval/Playground、搜索过滤、版本管理、响应式与可访问性（Phase S1–S8）

已完成或暂无待办的模块不保留空 TODO 文件；历史记录请查看 Git，稳定设计请优先查看 `docs/architecture/`、`docs/security/`、`docs/acceptance/`。
