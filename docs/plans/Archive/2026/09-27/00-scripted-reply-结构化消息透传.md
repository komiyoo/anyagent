---
type: Plan
title: Scripted Reply 结构化消息透传
description: ScriptedReply 的可选出站消息属性经 Response 消息项传到 connector；纯文本保持原样。
resource: docs/plans/Archive/2026/09-27/00-scripted-reply-结构化消息透传.md
tags: [计划]
generated: { by: plan-docs/v2, at: "2026-09-27T19:43:04+08:00" }
status: stable
sources:
  - id: runtime
    resource: docs/architecture/runtime/agent-packs-and-runtime-config.md
    title: Runtime · scripted_reply_providers
  - id: connector
    resource: docs/architecture/integrations/platform-connectors.md
    title: Platform Connectors
---

# Scripted Reply 结构化消息透传

## Context

`ScriptedReply` 目前只携带文本；Chatwoot 结构化消息还需 `content_type` 与 `content_attributes`。现有 connector 在 `/v1/responses` 后提取文字并调用 `send_message`，后者尚未传出属性。契约以 [runtime scripted reply](../../../../architecture/runtime/agent-packs-and-runtime-config.md#runtimescripted_reply_providers) 和 [connector contract](../../../../architecture/integrations/platform-connectors.md#connector-contract-interfaces) 为准。

## Approach

协议增加可选消息类型与属性，仅 scripted 命中时将其放在 Response 的 assistant message item 上；Chatwoot connector 提取后通过既有 `send_message` 的 `metadata` 参数发送。未提供属性时输出形状及发送参数保持原样。选项生成与点选事件处理由消费侧负责。

## Files

- `packages/anyagent/src/anyagent/protocol/scripted_reply.py`：协议字段。
- `packages/anyagent/src/anyagent/agent_runtime/loop/run.py` 与 `packages/anyagent/src/anyagent/server/routes/responses.py`：合成输出。
- `packages/anyagent/src/anyagent/plugins/builtin/chatwoot_connector/`：消息属性到出站 API。
- `tests/unit/`、`tests/integration/server/`：带属性与纯文本回归。

## Steps

- [x] 协议、合成 Response、Chatwoot 出站透传与回归测试通过。
- [x] 更新 runtime/connector 文档、TODO 证据及文档检查。
- [x] 版本提升、完整门禁、commit/push，确认 Packages 产物。

## Verification

SDK 0.4.30 提交 `57a5b0d` 已推送到 Codeup `main`，`v0.4.30` 标签已推送。全量测试 `531 passed, 1 skipped`；commit/push hooks、TypeScript smoke/pack、wheel/sdist、文档检查均通过。消费侧 `uv lock --upgrade-package anyagent` 与 `uv sync --locked` 已从 Packages 安装 0.4.30，清除 `PYTHONPATH` 后全量测试 `176 passed, 1 skipped`、doctor `ok=true`。云效流水线运行状态未能直接查询，本次以 Packages 正式包可安装为发布证据。
