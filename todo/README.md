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

- `todo/security-compliance.md`：安全与合规，含 Credential Vault（`requirements.md#req-8`）
- `todo/sdk.md`：Client SDK + CLI（`requirements.md#req-4`）

已完成或暂无待办的模块不保留空 TODO 文件；历史记录请查看 Git，稳定设计请优先查看 `docs/architecture/`、`docs/security/`、`docs/acceptance/`。
