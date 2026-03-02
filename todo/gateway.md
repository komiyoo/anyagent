# Gateway TODO

对应需求：`requirements.md#req-6`

## 目标

- 将飞书/Discord/Telegram 等平台能力以 connector + channel tools 的形式注入 agent loop，并负责平台消息渲染与会话映射。

## 里程碑（Milestones）

- M1：单平台（例如飞书）收发消息闭环
- M2：多平台 connector 插件化与统一上下文
- M3：治理（限流/重试/可观测）与多 agent 路由

## 任务（Tasks）

- [x] P0 定义 connector 插件化生命周期与加载方式（Req: `requirements.md#req-6-1`）Impl: packages/anyagent/src/anyagent/plugins/loader.py:124；Module: gateway
  - refs: packages/anyagent/src/anyagent/gateway/plugins.py:52
- [x] P0 落地平台能力注入示例（先选定 1 个平台做 reference）（Req: `requirements.md#req-6-2`）Impl: plugins/feishu/plugin.py:170；Module: gateway
  - refs: apps/tool-runtime/src/anyagent_tool_runtime/http/app.py:46
- [x] P1 定义并实现会话/线程绑定策略（Req: `requirements.md#req-6-3`）Impl: packages/anyagent/src/anyagent/gateway/session.py:33；Module: gateway
  - refs: packages/anyagent/src/anyagent/gateway/sequencer.py:11
- [x] P1 实现多 agent 路由映射（agent_id mapping）（Req: `requirements.md#req-6-4`）Impl: packages/anyagent/src/anyagent/gateway/agent_routing.py:122；Module: gateway
  - refs: requirements.md:830

## 决策 & 争议点

- [x] 首个 reference 平台优先做飞书还是 Discord（影响后续 channel tools 的形态）— 先做飞书 reference（Req: `requirements.md#req-6-2`）
