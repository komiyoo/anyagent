# Multi-Runtime TODO

对应需求:`requirements.md#req-5`、`requirements.md#req-7`

## 目标

- 让 anyagent 协议在多 server runtime 实现下保持等价,以 reference conformance suite 为验收基线。

本文件不规划具体语言选型,只跟踪 conformance suite 的成熟度与第二 runtime 的接入条件。具体语言 SDK 工作在 `todo/sdk.md`。

## 当前事实

- 唯一 reference runtime:Python built-in server,`packages/anyagent/src/anyagent/server/app.py`
- Contract test 入口:`tests/contract/`
- Conformance fixtures:`tests/fixtures/sdk_conformance/`

## 里程碑

- M1:reference conformance suite 覆盖 Responses API / Stage Events / internal/admin API / Tool Runtime / storage replay
- M2:第二 runtime 候选选定 + ADR
- M3:第二 runtime 通过 reference conformance suite

## 任务

- [ ] P1 整理 reference conformance suite 入口文档,标注覆盖范围与已知缺口(Req: `requirements.md#req-5`、`requirements.md#req-7`)
- [ ] P2 评估第二 server runtime 候选(Go / Rust),落 ADR(前置:M1 完成)(Req: `requirements.md#req-5`)
- [ ] P3 [Phase 4] 第二 runtime PoC 接入 reference conformance suite(Req: `requirements.md#req-5`)

## 决策 & 争议点

- [ ] 第二 runtime 的优先目标:性能 vs 部署 footprint vs 生态语言
- [ ] Conformance suite 是放在本仓还是独立仓库

## 参考

- `docs/architecture/overview/roadmap.md` Phase 4 / Phase 5
- `docs/architecture/runtime/stateless-agent-service-architecture.md`
- `docs/architecture/api/sdk-compatibility-matrix.md`
