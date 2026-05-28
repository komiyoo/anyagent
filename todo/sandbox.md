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

## 任务

- [ ] P0 选定第二 backend 候选(container 或 microVM),落 ADR(Req: `requirements.md#req-12`)
- [ ] P0 实装第二 backend,跑通 SandboxPolicy / NetworkSandboxPolicy / ResourceLimits 全字段(Req: `requirements.md#req-12-1` ~ `requirements.md#req-12-8`)
- [ ] P1 整理 sandbox contract test 矩阵,作为后续 backend 接入基线(Req: `requirements.md#req-12`)

## 决策 & 争议点

- [ ] 第二 backend 候选:容器(Docker / containerd / runc 之一)vs microVM(Firecracker / Kata)
- [ ] LocalUnsafe 是否在生产 build 中保留(默认应禁用)

## 参考

- `docs/architecture/overview/roadmap.md` Phase 2
- `docs/architecture/runtime/sandbox-session-filesystem-design.md`
