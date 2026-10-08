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
- M1 已补齐 Responses API / Stage Events / internal-admin API / Tool Runtime / storage+multi-agent replay 的 reference contract 入口。
- M2 曾选定 Rust reference runtime PoC，2026-10-07 撤回并删除（PoC 只返回写死的 JSON，无法验证协议等价性），原因见 `docs/architecture/decisions/second-runtime-rust-reference.md`。M2 / M3 回到未开始，等真实需求出现再立项。

## 待处理

- 暂无。

## 参考

- `docs/architecture/overview/roadmap.md` Phase 4 / Phase 5
- `docs/architecture/runtime/stateless-agent-service-architecture.md`
- `docs/architecture/api/sdk-compatibility-matrix.md`
