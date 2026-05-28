# SDK TODO

对应需求:`requirements.md#req-4`

本文件只跟踪 **SDK 框架自身** 的工作:wire DTO 生成、namespace facade、conformance fixtures、多语言 scaffold。不承担业务示例、部署模板、消费侧验收 — 这些归各自消费仓库。

## 当前事实

- Python SDK public surface 位于 `packages/anyagent/src/anyagent/agent_api_client.py`
- Python SDK public model facade 位于 `packages/anyagent/src/anyagent/types/__init__.py`,wire-level 模型来自 `anyagent.protocol.*`
- Protocol schema / endpoint / OpenAPI 导出位于 `packages/anyagent/src/anyagent/protocol/schema_export.py`,脚本入口 `scripts/export_protocol_schema.py`
- TypeScript SDK scaffold 位于 `sdks/typescript/`,使用生成的 `generated/protocol-schema.json` 与 `generated/protocol-types.ts`
- SDK conformance fixtures 位于 `tests/fixtures/sdk_conformance/`,minimum matrix `tests/fixtures/sdk_conformance/minimum_matrix.json`
- SDK / protocol 边界测试位于 `tests/contract/test_sdk_import_boundaries.py` 与 `tests/contract/test_protocol_schema_export.py`

## 里程碑

- M1:Python + TypeScript 双 SDK 通过同一份 conformance fixture
- M2:conformance 覆盖 Responses API / Stage Events / Tool Runtime / storage replay 主路径
- M3:新语言 SDK 接入只需读 conformance fixture 即可对齐

## 待处理

### Phase 1 — Protocol & SDK Hardening

- [ ] P0 扩大跨语言 conformance fixture 覆盖到 Stage Events 全主路径与 Tool Runtime manifest/execute(Req: `requirements.md#req-4-4`、`requirements.md#req-6`)
- [ ] P0 TypeScript SDK 完成 Responses 创建/流式/取消、Skills、Tools、Agents 四个 namespace 的最小可用面与 smoke(Req: `requirements.md#req-4`)
- [ ] P1 把 `minimum_matrix.json` 升级为对外兼容承诺基线,文档中标注每条 fixture 对应的 protocol version(Req: `requirements.md#req-4`、`requirements.md#req-7`)

### Phase 1.5 — Agentic Ecosystem Hardening

- [ ] P1 SDK Skill Injection 支持:Python SDK 的 `AnyAgent` client 支持在请求中传递 skill mentions,server 侧解析后注入 agent context(Req: `requirements.md#req-4`)
- [ ] P1 SDK Tool Discovery 支持:Python SDK 暴露 `tools.search(query)` helper,消费 `core.tool_search` 的 deferred tool 发现能力(Req: `requirements.md#req-4`、`requirements.md#req-5-2-1`)
- [ ] P2 SDK 配置层级感知:SDK client 初始化时支持读取 user/workspace 级配置合并结果,而非仅依赖显式参数(Req: `requirements.md#req-4`)

### Phase 4 — Ecosystem & Multi-Runtime

- [ ] P2 按真实集成需求添加 Go / Rust / Java 等 SDK scaffold;没有真实发布渠道前不创建空壳包(Req: `requirements.md#req-4`)

## 验证入口

```bash
rtk uv run --with pytest --project packages/anyagent python -m pytest tests/contract tests/unit/test_agent_api_client_control_plane.py -q
rtk uv run --project packages/anyagent python tests/acceptance/sdk/acceptance_anyagent_client_surface_smoke.py
rtk npm --prefix sdks/typescript run smoke
```

## 决策 & 争议点

- [ ] 多语言 SDK 的代码生成策略:全部从 schema 生成 vs 部分手写 helper

## 参考

- `docs/architecture/overview/roadmap.md` Phase 1 / Phase 4
- `docs/architecture/decisions/single-repo-multi-package-boundary.md`
- `docs/architecture/api/sdk-compatibility-matrix.md`
- `docs/architecture/api/sdk-public-surface.md`
