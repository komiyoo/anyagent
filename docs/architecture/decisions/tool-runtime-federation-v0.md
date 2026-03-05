<!--
---
doc_kind: architecture
status: stable
tags: ["tool-runtime", "federation", "registry", "credentials", "adr"]
summary: 固化 Tool Runtime v0 联邦边界：单服务部署、静态注册、无热更新控制面、Admin API 内嵌。
req: ["requirements.md#req-5-2-1", "requirements.md#req-5-3", "requirements.md#req-8"]
---
-->

# ADR: Tool Runtime Federation Boundary（v0）

Status: Accepted  
Date: 2026-03-05  
Scope: Tool Runtime / Security / Ops

## 决策结论

1. v0 固化为 **单 Tool Runtime 服务进程**（router + executors 同进程），不做远程 executor 控制面。  
2. v0 不实现 `/internal/tools/register`、`/internal/tools/heartbeat` 热更新控制面。  
3. Tool registry 采用启动期静态注册 + manifest 短 TTL 缓存 + `toolset_version_mismatch` 单次重试恢复。  
4. 凭证管理 Admin API 在 v1 继续内嵌 Tool Runtime；v2 若满足运维规模阈值再考虑独立服务拆分。

## 为什么这样定

- 先保证 execute/manifest 语义稳定与可观测闭环，避免过早引入控制面复杂度。
- 当前需求侧的主要痛点是“可靠执行与审计”，不是“分钟级动态注册”。
- Admin API 内嵌可以最小化部署复杂度，利于中小规模环境快速落地。

## 风险与缓解

- 风险：插件/工具变更需重启。  
  缓解：通过 manifest 缓存短 TTL + mismatch 自动刷新降低切换影响。
- 风险：Admin API 与执行面同进程增加 blast radius。  
  缓解：独立 `ADMIN_API_KEY`，并在后续引入分级网络访问控制。

## 触发 v2 拆分条件（建议）

- 需要分钟级工具热更新且不可接受重启窗口。
- 多租户场景下 Admin 操作面需要独立审计域与隔离域。
- 单进程 Tool Runtime 的资源争用已形成稳定瓶颈（有压测证据）。
