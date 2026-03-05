# Backlog / 未分配 TODO

本文件用于收集“暂时无法明确归属模块”的任务、想法与决策点；一旦归类清晰，应迁移到对应模块文件，并在迁移后把此处条目删除或标记为已迁移。

## Inbox（待分流）

- [x] P1 SDK 接入侧与 Agent Server 对齐 OpenAI Responses API（已分流）（迁移到：`todo/sdk.md`；Impl: `todo/sdk.md:1`；Module: `sdk`）
- [x] P1 对接 Anthropic Claude ModelProvider（Req: `TBD`；Impl: `packages/anyagent/src/anyagent/agent_runtime/model_providers/anthropic_messages.py:1`；Module: `packages/anyagent`）
  - refs: `packages/anyagent/src/anyagent/agent_runtime/model_providers/__init__.py:1`
- [x] P1 对接 Google Gemini ModelProvider（Req: `TBD`；Impl: `packages/anyagent/src/anyagent/agent_runtime/model_providers/google_gemini.py:1`；Module: `packages/anyagent`）
  - refs: `packages/anyagent/src/anyagent/agent_runtime/model_providers/__init__.py:53`

## Needs Triage（需要先澄清/拆解）

- [x] P0 [needs-design] 对外接口策略收敛：OpenAI Responses First + AnyAgent SDK Superset（Req: `requirements.md#req-4-1`；迁移到：`docs/architecture/decisions/openai-first-api-surface.md`；Impl: `docs/architecture/decisions/openai-first-api-surface.md:1`；Module: `architecture/sdk`）
- [x] P1 [needs-design] CI 质量门分层（离线 smoke 与文档护栏）与工作流落地（Req: `requirements.md#req-9`；迁移到：`docs/architecture/engineering/ci-pipeline.md`；Impl: `docs/architecture/engineering/ci-pipeline.md:1`；Module: `architecture/engineering`）

## 决策清单（建议用问题句）

- [x] Tool Runtime 热更新与联邦边界如何取舍（v0）？（Req: `requirements.md#req-5-2-1`，`requirements.md#req-5-3`；Impl: `docs/architecture/decisions/tool-runtime-federation-v0.md:1`；Module: `architecture/tool-runtime`）
- [x] Skills 选择是否允许隐式触发（v0）？（Req: `requirements.md#req-12-6`；Impl: `docs/architecture/decisions/skills-selection-policy.md:1`；Module: `architecture/skills`）

## 已归档（可选）

- [x] 以上决策条目均已迁移到模块 TODO 与 ADR 文档（Impl: `docs/architecture/decisions/README.md:1`；Module: `architecture`）
