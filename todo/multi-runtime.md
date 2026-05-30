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

## 当前状态

- 已完成条目已清理,历史记录请查看 Git。
- 已实现能力的长期口径见架构文档:
  - reference conformance suite 入口、覆盖范围与已知缺口:`docs/architecture/testing/testing-strategy.md`、`tests/contract/README.md`
  - conformance suite 随 protocol/schema bundle 留在本仓的决策:`docs/architecture/decisions/protocol-versioning.md`、`docs/architecture/decisions/`
- M1 已补齐 Responses API / Stage Events / internal-admin API / Tool Runtime / storage+multi-agent replay 的 reference contract 入口；第二 runtime 候选已选 Rust reference runtime PoC。

## 待处理

- [x] P2 评估第二 server runtime 候选(Go / Rust),落 ADR(前置:M1 完成)(Req: `requirements.md#req-5`；Module: `server-runtime`；Impl: `docs/architecture/decisions/second-runtime-rust-reference.md:18`、`docs/architecture/testing/testing-strategy.md:110`)
- [x] P3 [Phase 4] 第二 runtime PoC 接入 reference conformance suite(Req: `requirements.md#req-5`；Module: `server-runtime`；Impl: `runtimes/rust-reference/conformance.json:1`、`tests/contract/test_second_runtime_poc.py:13`)

## 决策 & 争议点

- [x] 第二 runtime 的优先目标:性能 vs 部署 footprint vs 生态语言：优先部署 footprint 与协议/状态机可验证性，选 Rust；Go 作为后续 SDK 或第三 runtime 重新评估。（Module: `server-runtime`；Impl: `docs/architecture/decisions/second-runtime-rust-reference.md:29`）

## 参考

- `docs/architecture/overview/roadmap.md` Phase 4 / Phase 5
- `docs/architecture/runtime/stateless-agent-service-architecture.md`
- `docs/architecture/api/sdk-compatibility-matrix.md`
