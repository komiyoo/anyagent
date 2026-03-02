# 安全与合规 TODO

对应需求：`requirements.md#req-8`

## 目标

- 明确并落实对外接口鉴权、工具执行安全边界、审计与合规要求。

## 里程碑（Milestones）

- M1：鉴权/权限模型清晰 + 默认拒绝
- M2：sandbox 工具最小权限与隔离到位
- M3：审计与告警可用

## 任务（Tasks）

- [x] P0 明确威胁模型与外部输入校验边界（Req: `requirements.md#req-8`；Impl: `docs/security/security-threat-model.md:1`；Module: `docs`）
- [x] P0 落地 sandbox 工具最小安全要求与默认策略（Req: `requirements.md#req-5-5`，`requirements.md#req-8`；Impl: `docs/security/sandbox-security.md:1`, `apps/tool-runtime/src/anyagent_tool_runtime/http/app.py:36`；Module: `tool-runtime/docs`）
- [x] P1 落地工具权限与策略（policy）体系（Req: `requirements.md#req-5-10`，`requirements.md#req-8`；Impl: `apps/tool-runtime/src/anyagent_tool_runtime/runtime/policy.py:13`, `docs/security/tool-policy.md:1`；Module: `tool-runtime/docs`）
- [x] P2 落地审计事件与敏感操作留痕（Req: `requirements.md#req-5-13`，`requirements.md#req-8`；Impl: `apps/tool-runtime/src/anyagent_tool_runtime/runtime/executors.py:55`, `docs/security/audit-logging.md:1`；Module: `tool-runtime/docs`）
