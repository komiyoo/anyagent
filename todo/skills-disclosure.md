# Skills / 动态披露 TODO

对应需求：`requirements.md#req-12`

## 目标

- 让 skills 能按需加载与注入，并且工具披露遵循“最小暴露面”，与 Tool Runtime 的 policy 保持一致。

## 里程碑（Milestones）

- M1：skills 包结构 + roots/scope 加载可用
- M2：动态披露（选择/注入/披露）机制可用
- M3：与 Tool Runtime manifest/execute 全链路对齐

## 任务（Tasks）

- [ ] P0 定义并实现 skill 包结构与解析（SKILL.md + 可选元数据）（Req: `requirements.md#req-12-1`）
- [ ] P0 定义并实现 skill roots 与 scope（Repo/User/System/Admin）加载顺序（Req: `requirements.md#req-12-2`）
- [ ] P1 实现 skills enable/disable 配置与生效机制（Req: `requirements.md#req-12-3`）
- [ ] P1 实现 skill dependencies（tools）解析与约束（Req: `requirements.md#req-12-4`）
- [ ] P1 实现 skill permissions 与 sandbox/tool policy 交互（Req: `requirements.md#req-12-5`）
- [ ] P1 落地动态披露：选择技能（Req: `requirements.md#req-12-6-1`）
- [ ] P1 落地动态披露：注入技能指令（Req: `requirements.md#req-12-6-2`）
- [ ] P1 落地动态披露：披露工具（Req: `requirements.md#req-12-6-3`）
- [ ] P2 定义并实现 `GET /internal/skills/list`（给 Gateway/UI）（Req: `requirements.md#req-12-7`）
- [ ] P2 梳理并固化与 Tool Runtime 的交互关系（manifest -> tools[]）（Req: `requirements.md#req-12-8`）

## 决策 & 争议点

- [ ] 技能选择策略：显式 mention vs 自动推荐（v0 哪些场景允许隐式）（Req: `requirements.md#req-12-6`）

