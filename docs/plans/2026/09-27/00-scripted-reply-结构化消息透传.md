---
type: Plan
title: Scripted Reply 结构化消息透传
description: ScriptedReply 的可选出站消息属性经 Response 消息项传到 connector；纯文本保持原样。
resource: docs/plans/2026/09-27/00-scripted-reply-结构化消息透传.md
tags: [计划]
generated: { by: plan-docs/v2, at: "2026-09-27T19:43:04+08:00" }
status: draft
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

`ScriptedReply` 目前只携带文本；Chatwoot 结构化消息还需 `content_type` 与 `content_attributes`。现有 connector 在 `/v1/responses` 后提取文字并调用 `send_message`，后者尚未传出属性。契约以 [runtime scripted reply](../../../architecture/runtime/agent-packs-and-runtime-config.md#runtimescripted_reply_providers) 和 [connector contract](../../../architecture/integrations/platform-connectors.md#connector-contract-interfaces) 为准。

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
- [ ] 版本提升、完整门禁、commit/push，确认 Packages 产物。

## Verification

运行 SDK 单测及集成测试、`scripts/anyagent-dev-cli` 文档与版本检查；按仓库 hook 完成提交和推送门禁。消费侧从 Packages 安装新版本后再验收。
