<!--
---
doc_kind: architecture
status: stable
tags: ["skills", "dynamic-disclosure", "tool-disclosure", "prompt"]
summary: Skills 包结构、roots/scope、enable/disable、dependencies、permissions、选择、注入与工具披露机制。
req: ["requirements.md#req-12", "requirements.md#req-12-1", "requirements.md#req-12-6"]
---
-->

# Skills Dynamic Disclosure

Skills 不默认全量注入，也不默认披露其依赖工具。只有技能被选中或触发时，AgentRuntime 才注入技能指令，并通过 Tool Runtime manifest 请求最终可见工具集合。

## Skill 包结构

每个 skill 至少包含：

- `SKILL.md`
  - YAML front matter。
  - 必填：`name`、`description`。
  - 可选：`metadata.short-description`。
  - body：技能指令正文。

可选元数据：

- `agents/openai.yaml`
  - `interface`：UI 展示信息。
  - `dependencies.tools[]`：工具依赖。
  - `policy.allow_implicit_invocation`：是否允许隐式触发。
  - `permissions`：网络、文件系统、sandbox 等权限档案。

`SKILL.md` 是唯一必需文件；`agents/openai.yaml` 解析失败应 fail-open，忽略元数据但仍可加载技能正文。

## Skill Roots 与 Scope

roots 与优先级：

1. Agent：`<workspace_dir>/.anyagent/agents/<agent_id>/skills/**/SKILL.md`
2. Repo：`<workspace_dir>/.anyagent/skills/**/SKILL.md`
3. Admin：`<tenant_shared_dir>/skills/**/SKILL.md`
4. System：`/opt/agents/skills/**/SKILL.md`
5. User：`~/.anyagent/skills/**/SKILL.md`

约束：

- 同一个 canonical `SKILL.md` path 只加载一次。
- 同名技能默认不允许并存；按 scope/root 优先级保留一份可见项，其余记入 loading errors。

## Skills Enable/Disable

配置粒度以 skill name 为 key；服务端在当前可见技能集合上解析到唯一 stable id。

来源：

- User 配置层。
- SessionFlags，优先级高于 User。

内部执行仍以 canonical path 或 stable id 为 key。

## Skill Dependencies

`dependencies.tools[]` 用于：

- 让 Gateway/UI 在披露技能前知道技能会用到哪些工具。
- 技能选中后向 Tool Runtime 请求 manifest。
- 技能选中后确认相应 executor 可用。

建议映射：

- `transport="core"` -> `core.*`
- `transport="app"` -> `app.*`
- `transport="sandbox"` -> `exec`
- `transport="channel"` -> `<channel>.*`
- `transport="mcp"` -> `mcp.<server_label>.*`

## Skill Permissions

skill 可以声明权限档案，例如网络与文件系统读写。技能被选中时：

- 可以在全局上限内扩大或收缩 `exec` tool 的 sandbox 权限边界。
- 不得越权打开 tenant/global deny 的能力。

## 动态披露机制

动态披露分三步：

1. 选择技能。
2. 注入技能指令。
3. 披露工具。

### 选择技能

技能选择来源按优先级累加：

- AgentSpec 默认技能：`agent.yaml` 的 `skills.default_selected`。
- 显式选择：`metadata.skills`，可为 skill name 或 `skill://.../SKILL.md`。
- 文本 mention：例如 `$skill-name`。
- 隐式触发：仅当 `policy.allow_implicit_invocation=true`。

规则：

- 各来源累加，按 stable id/path 去重。
- 未找到、被禁用或歧义命中的技能必须跳过，并产生可审计 decision。

### 注入技能指令

技能被选中时，AgentRuntime 将 `SKILL.md` 正文注入本次 run 上下文：

- 注入位置：用户消息之前。
- 推荐角色：`developer`，必要时退化为独立 system block。
- 注入内容包含 skill name/path、stable id、sha256 与正文。
- 注入是 per-run 的，不污染其他 session 默认 prompt。
- 读文件失败应产生 warning，默认 fail-open。

### 披露工具

技能被选中时，AgentRuntime 把希望披露的工具名集合提交给 Tool Runtime manifest。

工具来源并集：

- 基础 core 工具。
- channel 工具。
- skill dependencies。
- 外部请求中声明的 function tool names。

最终可见集合必须由 Tool Runtime policy/registry 决定。

## 内部 API skills/list

`GET /internal/skills/list?session_key=...` 用于 Gateway/UI 展示技能列表与依赖工具。

返回字段建议：

- `stable_id`
- `name`
- `description`
- `short_description`
- `interface`
- `dependencies`
- `scope`
- `path` 或 server 内部 `skill_id`
- `source_hash`
- `enabled`
- `errors`

多租户场景下不应默认返回绝对路径。
