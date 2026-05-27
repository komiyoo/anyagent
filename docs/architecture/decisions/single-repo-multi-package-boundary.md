<!--
---
doc_kind: architecture
status: accepted
tags: ["repo-boundary", "sdk", "protocol", "studio", "packaging", "adr"]
summary: anyagent 保持单仓库协作，通过协议真源、多包边界和 contract tests 支撑 server/client/studio 与多语言 SDK；暂不拆为独立 repo。
req: ["requirements.md#0-1-仓库边界", "requirements.md#req-4"]
---
-->

# ADR: Single Repo, Multi-Package Boundary

Status: Accepted
Date: 2026-05-27
Updated: 2026-05-27
Scope: Repository boundary / packaging / SDK / Studio

## 背景

anyagent 当前同时承载 Server Core、Python Client SDK、Protocol SSOT、CLI、内置 Studio，并在同仓库内包含 TypeScript SDK scaffold。

直接把 `server`、`client`、`studio` 拆成独立 repo 会过早引入跨 repo 发布、contract 漂移和联调成本。当前更重要的边界不是 repo 数量，而是：

- wire contract 是否有单一真源；
- server、SDK、Studio 是否只通过公开 contract 协作；
- 多语言 SDK 是否能从同一份 spec/model 生成或校验；
- 每次协议变更是否能在同一轮变更里更新 server、SDK、Studio 与 contract tests。

## 决策

anyagent 保持单仓库协作，不按 `server/client/studio` 拆分为独立 repo。当前已落地的“单仓、多包、协议先行”组织方式：

```text
anyagent/
  packages/
    anyagent/                  # Python distribution：server + CLI + Python SDK + protocol + bundled Studio static
  sdks/
    typescript/                # 从 protocol schema bundle 生成类型并提供 fetch client scaffold
  tests/
    contract/                  # protocol/spec/SDK 兼容契约
    fixtures/sdk_conformance/  # 跨 SDK 共享 fixture 与 minimum matrix
```

## 边界规则

1. `anyagent.protocol.*` 继续作为 wire-level SSOT。新增或修改 HTTP body、SSE event、admin/internal API、StageEvent、Tool Runtime contract 时，先改协议模型或 spec export，再改 server/SDK/Studio。
2. Python SDK 的 public model facade 从 `anyagent.types` 暴露；它可以重导出 protocol model，但不得重新定义 wire 字段。
3. Studio 只消费 OpenAI Responses API、`/internal/*` 与 `/admin/*` typed API，不读取 server 内部 Python 模块，也不复制协议 shape。
4. 多语言 SDK 放在同 repo 的 `sdks/<language>/`，共享同一份 protocol/spec、contract tests 和 acceptance fixtures。
5. server runtime 可以依赖 protocol；SDK 和 Studio 不得依赖 server runtime。
6. Python distribution 打包 Studio static bundle；Studio source 位于 `packages/anyagent/studio/`，并通过 `package.json` 暴露独立 `dev` / `build` script 入口。

## 已实现的 Contract Surface

| Surface | 实现 | 验证 |
|---|---|---|
| Protocol schema bundle | `packages/anyagent/src/anyagent/protocol/schema_export.py` | `tests/contract/test_protocol_schema_export.py` |
| OpenAPI 3.1 export | `scripts/export_protocol_schema.py --format openapi` | `tests/contract/test_protocol_schema_export.py` |
| Endpoint manifest | `export_protocol_endpoints()` | `tests/contract/test_protocol_schema_export.py` |
| Python SDK typed facade | `packages/anyagent/src/anyagent/types/__init__.py` | `tests/contract/test_sdk_import_boundaries.py` |
| Python SDK client | `packages/anyagent/src/anyagent/agent_api_client.py` | `tests/unit/test_agent_api_client_control_plane.py` |
| Studio source/static | `packages/anyagent/studio/`、`packages/anyagent/src/anyagent/studio_static/` | `packages/anyagent/studio/package.json`、`packages/anyagent/src/anyagent/server/app.py` |
| TypeScript SDK scaffold | `sdks/typescript/` | `npm --prefix sdks/typescript run smoke` |
| Shared conformance fixtures | `tests/fixtures/sdk_conformance/` | `tests/contract/test_protocol_schema_export.py` |

The protocol bundle exports Pydantic model schemas, type-adapter schemas, semantic rules, and endpoint metadata. The TypeScript SDK consumes the generated bundle, validates schema-backed request/response payloads, and resolves schema-backed helper paths through the endpoint manifest. The Studio source and bundled static assets remain in the Python package workspace, but this ADR's boundary is repo/package/API ownership rather than Studio UI build health.

## Repo 拆分门槛

只有同时满足以下条件，才重新评估拆 repo：

- protocol/spec 已能独立版本化和发布；
- server 与至少一个 SDK 已经出现明显不同的发布节奏；
- SDK 不需要 import server runtime，Studio 不需要共享 server 内部代码；
- 跨 repo contract tests 可在 CI 中自动验证；
- release ownership、issue 流和安全响应流程已经分离。

## 不选方案

1. **立即拆成 server/client/studio 三个 repo**：不选。当前协议仍在快速演进，跨 repo 会放大 drift 和发布顺序成本。
2. **继续把所有边界都视作单一 Python 包内部细节**：不选。多语言 SDK 和 Studio 都要求公开 contract 可发现、可生成、可测试。
3. **每个语言 SDK 各自手写协议模型**：不选。会破坏 Protocol SSOT，导致字段、事件和错误语义漂移。

## 验证入口

```bash
rtk python3 scripts/docs/check.py --root . --check-index --check-code-refs
rtk uv run --with pytest --project packages/anyagent python -m pytest tests/contract tests/unit/test_agent_api_client_control_plane.py -q
rtk uv run --project packages/anyagent python tests/acceptance/sdk/acceptance_anyagent_client_surface_smoke.py
rtk npm --prefix sdks/typescript run smoke
```
