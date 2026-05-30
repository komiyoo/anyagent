# Sandbox TODO

对应需求:`requirements.md#req-12`

## 目标

- `SandboxPolicy` / `NetworkSandboxPolicy` / `ResourceLimits` 不绑定单一执行后端;agent loop 只消费 `exec` tool 与 sandbox policy。

## 当前事实

- 协议模型:`packages/anyagent/src/anyagent/protocol/sandbox.py`
- 后端实现:`packages/anyagent/src/anyagent/server/sandbox/`(SandboxManager + OpenSandbox / External / LocalUnsafe)
- 长期设计:`docs/architecture/runtime/sandbox-session-filesystem-design.md`

## 里程碑

- M1:第二 backend(容器或 microVM 之一)实装,通过 contract test
- M2:网络 sandbox policy 在两种 backend 下行为一致
- M3:资源限制(CPU / memory / wall-clock)在两种 backend 下行为一致

## 当前状态

- 已完成条目已清理,历史记录请查看 Git。
- 已实现能力的长期口径见架构文档:
  - sandbox / session filesystem 设计、contract test 矩阵、LocalUnsafe 定位:`docs/architecture/runtime/sandbox-session-filesystem-design.md`
  - 第二 backend 候选选型(OpenSandbox on Kubernetes):`docs/architecture/decisions/sandbox-backend-selection.md`

## 待处理

- 本模块当前无未完成任务。

## 参考

- `docs/architecture/overview/roadmap.md` Phase 2
- `docs/architecture/runtime/sandbox-session-filesystem-design.md`
