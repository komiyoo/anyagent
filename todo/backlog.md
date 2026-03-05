# Backlog / 未分配 TODO

本文件用于收集“暂时无法明确归属模块”的任务、想法与决策点；一旦归类清晰，应迁移到对应模块文件，并在迁移后把此处条目删除或标记为已迁移。

## Inbox（待分流）

- [x] P1 SDK 接入侧与 Agent Server 对齐 OpenAI Responses API（已分流）（迁移到：`todo/sdk.md`；Impl: `todo/sdk.md:1`；Module: `sdk`）
- [x] P1 对接 Anthropic Claude ModelProvider（Req: `TBD`；Impl: `packages/anyagent/src/anyagent/agent_runtime/model_providers/anthropic_messages.py:1`；Module: `packages/anyagent`）
  - refs: `packages/anyagent/src/anyagent/agent_runtime/model_providers/__init__.py:1`
- [x] P1 对接 Google Gemini ModelProvider（Req: `TBD`；Impl: `packages/anyagent/src/anyagent/agent_runtime/model_providers/google_gemini.py:1`；Module: `packages/anyagent`）
  - refs: `packages/anyagent/src/anyagent/agent_runtime/model_providers/__init__.py:53`

## Needs Triage（需要先澄清/拆解）

- [ ] P0 [needs-design] <需要产品/架构决策的问题>（Req: `requirements.md#req-...` 或 `TBD`）
- [ ] P1 [blocked] <依赖外部输入/资源的事项>（依赖：<填>）

## 决策清单（建议用问题句）

- [ ] <决策问题>：选项 A/B/C，各自 trade-off 是什么？（Req: `requirements.md#req-...` 或 `TBD`）

## 已归档（可选）

- [ ] <已完成/已迁移的条目>（迁移到：`todo/<module>.md`）
