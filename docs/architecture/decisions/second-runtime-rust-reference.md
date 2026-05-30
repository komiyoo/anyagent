<!--
---
doc_kind: architecture
status: stable
tags: ["multi-runtime", "rust", "conformance", "adr"]
summary: 第二 server runtime 候选选定 Rust reference runtime PoC，以 conformance target 接入 reference suite。
req: ["requirements.md#req-5", "requirements.md#req-7"]
---
-->

# ADR: Second Runtime Candidate

Status: Accepted  
Date: 2026-05-30  
Req: `requirements.md#req-5`, `requirements.md#req-7`  
Scope: Server Runtime / Reference Conformance Suite

## 决策结论

第二 server runtime 候选选定 **Rust reference runtime**。

首个 PoC 范围是协议与控制面 conformance target，而不是完整 agent loop：

- 提供可独立编译的 `runtimes/rust-reference` crate。
- 以静态、无外部依赖的 Rust HTTP/JSON surface 验证 runtime target packaging、health/admin/tool catalog 最小行为。
- 通过 `runtimes/rust-reference/conformance.json` 接入 reference conformance suite，声明当前覆盖与缺口。
- 完整 Responses API、Tool Runtime execute、storage adapter 和 model provider loop 必须等 conformance target 能稳定运行后再扩大。

## 为什么选 Rust

- 部署 footprint 更低，适合作为 future sidecar / edge / single-binary runtime。
- 类型系统与所有权模型适合实现协议边界、storage lease、stream replay 和 sandbox lifecycle 这类状态机。
- 本仓当前可用工具链已有 `rustc` / `cargo`，可以在 CI 中先建立 build/test gate；Go 工具链当前未就绪。

## 暂不选 Go 的原因

Go 仍适合运维生态和云原生团队，但本轮第二 runtime 的优先目标不是最快落业务 API，而是建立“非 Python runtime 能否被 reference conformance suite 管住”的最小闭环。Go 可作为后续 SDK 或第三 runtime 重新评估。

## Conformance Gate

第二 runtime PoC 的最低门槛：

- `cargo test --manifest-path runtimes/rust-reference/Cargo.toml` 通过。
- `tests/contract/test_second_runtime_poc.py` 能发现 conformance target，并确认其声明覆盖 admin/internal/storage-replay 缺口的接入状态。
- 新增 public wire contract 时，先扩展 Python reference contract，再由 Rust target 标注 unsupported / partial / supported。

## 风险与缓解

- 风险：Rust PoC 变成第二套未完成业务实现。  
  缓解：PoC 仅允许实现 conformance target 所需最小 surface，禁止复制 Python runtime 内部逻辑。
- 风险：双 runtime schema 漂移。  
  缓解：Rust target 不定义独立协议模型，必须消费 `protocol-schema.json` 或 conformance fixtures。
- 风险：维护成本过早上升。  
  缓解：PoC 状态保持 preview；未通过 reference suite 前不承诺生产替代。
