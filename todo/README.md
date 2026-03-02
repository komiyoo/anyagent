# TODO（按模块拆分）

本目录用于用 **Markdown checkbox** 维护 AnyAgent 的工程任务，并且让每条任务都能追溯到需求文档 `requirements.md` 的稳定锚点（方案 B）。

## 约定

### 1) 单一真源（Single Source of Truth）

- 需求真源：`requirements.md`
- 任务真源：`todo/*.md`
- TODO 文件里的每条任务应尽量附带需求引用：`requirements.md#req-...`
- 进度默认按文件内顺序（从上到下）理解：新增任务建议**追加到末尾**，避免频繁重排导致“做到第几个”含义漂移

> 说明：本仓库当前没有 `AnyAgent/requirements.md`，因此这里使用 `requirements.md` 作为 canonical 路径。若后续迁移为 monorepo 子目录结构，再批量替换链接目标即可。

### 2) 锚点命名规则（稳定链接）

需求文档在关键标题前插入了显式锚点，例如：

- `requirements.md#req-4`（第 4 节）
- `requirements.md#req-4-4`（第 4.4 节）
- `requirements.md#req-5-8-1`（第 5.8.1 节）

### 3) 任务条目格式（推荐）

每条任务一行，带 checkbox + 优先级 + 需求引用（可选加状态标签）：

- `- [ ] P0 <任务>（Req: requirements.md#req-...）`
- `- [ ] P1 <任务>（Req: requirements.md#req-...）`
- `- [ ] P2 <任务>（Req: requirements.md#req-...）`

完成时必须补齐“实现证据”字段（便于复盘、避免口头完成）：

- `- [x] P0 <任务>（Req: requirements.md#req-...；Impl: <path:line>；Module: <module>）`

其中：

- `Impl:`：实现证据，推荐写成 `path:line`（例如 `apps/agent-api/src/server.ts:42`）
- `Module:`：模块名（例如 `agent-api/tool-runtime/gateway/skills/multi-agent/security/tests/concurrency`）

可选标签（用方括号即可，便于全文检索）：

- `[blocked]`：依赖未满足
- `[needs-design]`：需要先补设计/决策
- `[waiting]`：等待外部输入/评审

### 4) 分流规则（Backlog -> 模块）

- 新想法/新需求先落在 `todo/backlog.md`，确保“不丢”。
- 一旦能明确归属模块（Agent API / Tool Runtime / Gateway / Skills / Multi-Agent / 安全 / 并发 / 测试），就迁移到对应 `todo/<module>.md`。
- 迁移时强制补齐 `Req: requirements.md#req-*`（或明确写 `TBD` 并说明原因），避免后续断链与“无法验收”。

## 模块文件

- `todo/backlog.md`：未分配/待分流的事项收集箱（先收集，再迁移到具体模块）
- `todo/agent-api.md`：对外 Responses API 兼容（对应 `requirements.md#req-4`）
- `todo/tool-runtime.md`：内部 Tool Runtime 协议与执行（对应 `requirements.md#req-5`）
- `todo/gateway.md`：平台接入与消息交互（对应 `requirements.md#req-6`）
- `todo/concurrency-reliability.md`：并发与可靠性（对应 `requirements.md#req-7`）
- `todo/security-compliance.md`：安全与合规（对应 `requirements.md#req-8`）
- `todo/tests-acceptance.md`：测试与验收（对应 `requirements.md#req-9`）
- `todo/skills-disclosure.md`：Skills 加载与动态披露（对应 `requirements.md#req-12`）
- `todo/multi-agent.md`：Multi-Agent（对应 `requirements.md#req-13`）

## 新增一个模块 TODO 文件

复制模板：`todo/_template.md`，重命名为你的模块文件名，并在此 README 的“模块文件”列表里补一行即可。
