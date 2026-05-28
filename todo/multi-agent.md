# Multi-Agent TODO

对应需求:`requirements.md#req-13`

## 目标

- parent / child / root run、quota、event replay 语义在 reference runtime 上可验收,作为后续多 runtime / 多 SDK 的兼容基线。

## 当前事实

- Runtime primitives:`packages/anyagent/src/anyagent/agent_runtime/`
- Stage Events:`anyagent.protocol.events`
- 长期文档:`docs/architecture/multi-agent/`

## 里程碑

- M1:parent / child / root run 语义在 reference runtime 跑通
- M2:quota 与 event replay 在跨节点存储组合下一致
- M3:Multi-Agent contract test 套件成为新 runtime 接入门槛

## 任务

- [ ] P1 整理 parent / child / root run 语义文档与 contract test 入口(Req: `requirements.md#req-13`、`requirements.md#req-13-1` ~ `requirements.md#req-13-8`)
- [ ] P1 quota 语义在跨节点 storage 下的一致性验收(Req: `requirements.md#req-13`)
- [ ] P2 Event replay 在 multi-agent 场景下的语义验收(与 storage replay 共用 contract)(Req: `requirements.md#req-13`、`requirements.md#req-3-1`)

## 决策 & 争议点

- [ ] Multi-Agent 编排原语是否作为 protocol 一部分对外暴露,还是仅在 runtime 内部

## 参考

- `docs/architecture/overview/roadmap.md` Phase 4
- `docs/architecture/multi-agent/`
