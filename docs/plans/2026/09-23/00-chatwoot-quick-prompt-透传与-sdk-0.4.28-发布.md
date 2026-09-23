---
type: Plan
title: Chatwoot quick prompt 透传与 SDK 0.4.28 发布
description: 修复 Chatwoot quick prompt 字段透传，发布 Python SDK 并升级业务消费侧。
resource: docs/plans/2026/09-23/00-chatwoot-quick-prompt-透传与-sdk-0.4.28-发布.md
tags: [计划]
generated: { by: plan-docs/v2, at: "2026-09-23T08:24:44+08:00" }
status: stable
sources:
  - id: connectors
    resource: docs/architecture/integrations/platform-connectors.md
    title: Platform Connectors
  - id: release
    resource: docs/release-checklist.md
    title: Release Checklist
---

# Chatwoot quick prompt 透传与 SDK 0.4.28 发布

## 背景与实现

Chatwoot 的 quick prompt custom attribute 未进入 `chatwoot_page_context`，消费侧无法据此识别页面按钮。按 [connector 职责](../../../architecture/integrations/platform-connectors.md#connector-contract-interfaces) 修复共享提取函数，对应 `requirements.md#req-6`。

复用 `chatwoot.py` 的 `_chatwoot_custom_attributes` 与 `_set_str`，保留 `lt_quick_prompt_id` 和消费侧已支持的 `quick_prompt_id`。既有 metadata 传递和平台事件记录共用该函数，无需增加业务路由逻辑。

## 文件与步骤

- [x] 在 `tests/unit/gateway/test_connector_contracts.py` 和 `tests/integration/server/test_chatwoot_connector_flow.py` 复现字段丢失，修复 `packages/anyagent/src/anyagent/plugins/builtin/chatwoot_connector/chatwoot.py`，同步 connector README 与 `todo/server-runtime.md`。修复前 6 项失败；修复后两份测试共 59 项通过。
- [x] 用 `scripts/anyagent-dev-cli version bump` dry-run 后升至 0.4.28，更新 lock，完成测试与构建：`pytest tests -q` 为 524 passed、1 skipped；`uv build --project packages/anyagent` 成功。
- [ ] 按 [发布清单](../../../release-checklist.md#checklist) 提交并 push，保留 commit/push hooks。
- [ ] 核实 Yunxiao Packages 发布，升级 `../lt-anyagent-wks` 的依赖、lock 和当前版本文档，删除 quick prompt 兼容补丁并验收。

## 验证

- SDK 回归覆盖字符串校验、Chatwoot custom attribute 来源、请求 metadata 与平台事件；commit/push hooks 执行 docs、unit、regression、offline smoke。
- `uv build --project packages/anyagent` 验证 0.4.28 产物。
- 消费侧从 Packages 安装后执行 pytest、doctor、agent list 和 prompt bundle smoke；不向客户会话发送测试消息。
