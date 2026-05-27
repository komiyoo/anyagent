<!--
---
doc_kind: architecture
status: stable
tags: ["skills", "dynamic-disclosure", "policy", "adr"]
summary: 固化 v0 skills 选择策略：显式优先、隐式默认关闭、可审计决策链。
req: ["requirements.md#req-12-6"]
---
-->

# ADR: Skills Selection Policy（v0）

Status: Accepted  
Date: 2026-03-05  
Scope: Agent Runtime / Agent API / Skills Disclosure

## 决策结论

1. v0 默认 `allow_implicit_invocation=false`。  
2. 技能选择来源优先级与累加规则维持 `requirements.md#req-12-6`：
   - AgentSpec `default_selected`
   - `metadata.skills`
   - `$skill` 文本显式 mention
3. 文本 mention 仅在“唯一且 enabled”时生效，歧义必须拒绝自动选择。
4. 每个被跳过/拒绝的 skill 都要保留 machine-readable decision（用于审计和排障）。

## 为什么这样定

- 默认关闭隐式触发可显著降低误注入与越权披露风险。
- 显式输入优先，符合“最小意外原则”与可解释性要求。
- 保留审计决策链，有利于 UI 层做“为什么没选中某技能”的反馈。

## 扩展约束（非 v0）

- 仅当策略开关显式开启时，允许场景化隐式启用（例如工作区类型匹配）。
- 隐式启用前置条件：
  - 可解释（必须能输出触发原因）
  - 可回滚（可由调用方显式关闭）
  - 不扩大 Tool Runtime policy 的最终暴露面
