# SDK TODO

对应需求：`requirements.md#req-4`

## 当前事实

- Python SDK public surface 位于 `packages/anyagent/src/anyagent/agent_api_client.py`。
- SDK public model facade 位于 `packages/anyagent/src/anyagent/types/__init__.py`，wire-level 模型来自 `anyagent.protocol.*`。
- Protocol schema / endpoint / OpenAPI 导出位于 `packages/anyagent/src/anyagent/protocol/schema_export.py`，脚本入口是 `scripts/export_protocol_schema.py`。
- TypeScript SDK scaffold 位于 `sdks/typescript/`，使用生成的 `generated/protocol-schema.json` 与 `generated/protocol-types.ts`。
- SDK conformance fixtures 位于 `tests/fixtures/sdk_conformance/`。
- SDK/protocol 边界测试位于 `tests/contract/test_sdk_import_boundaries.py` 与 `tests/contract/test_protocol_schema_export.py`。

## 待处理

- [ ] P1 继续扩大跨语言 conformance fixture 的覆盖面；新增 fixture 时同步更新 `tests/fixtures/sdk_conformance/minimum_matrix.json`。
- [ ] P2 按真实集成需求添加 Go / Rust / Java 等 SDK scaffold；没有真实发布渠道前不创建空壳包。

## 验证入口

```bash
rtk uv run --with pytest --project packages/anyagent python -m pytest tests/contract tests/unit/test_agent_api_client_control_plane.py -q
rtk uv run --project packages/anyagent python tests/acceptance/sdk/acceptance_anyagent_client_surface_smoke.py
rtk npm --prefix sdks/typescript run smoke
```

## 参考

- `docs/architecture/decisions/single-repo-multi-package-boundary.md`
- `docs/architecture/api/sdk-compatibility-matrix.md`
- `docs/architecture/api/sdk-public-surface.md`
