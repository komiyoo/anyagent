# 安全与合规 TODO

对应需求：`requirements.md#req-8`

## 目标

- 明确并落实对外接口鉴权、工具执行安全边界、审计与合规要求。

## 里程碑（Milestones）

- M1：鉴权/权限模型清晰 + 默认拒绝
- M2：sandbox 工具最小权限与隔离到位
- M3：审计与告警可用

## 任务（Tasks）

- [ ] P0 明确威胁模型与外部输入校验边界（Req: `requirements.md#req-8`）
- [ ] P0 落地 sandbox 工具最小安全要求与默认策略（Req: `requirements.md#req-5-5`，`requirements.md#req-8`）
- [ ] P1 落地工具权限与策略（policy）体系（Req: `requirements.md#req-5-10`，`requirements.md#req-8`）
- [ ] P2 落地审计事件与敏感操作留痕（Req: `requirements.md#req-5-13`，`requirements.md#req-8`）

