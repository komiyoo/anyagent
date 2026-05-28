# Protocol TODO

对应需求:`requirements.md#req-4`、`requirements.md#req-7`

## 目标

- 让 `anyagent.protocol.*` 与 schema bundle 成为对外可承诺兼容性的协议真源。

## 当前事实

- 协议真源:`packages/anyagent/src/anyagent/protocol/`
- Schema 导出:`packages/anyagent/src/anyagent/protocol/schema_export.py`,脚本 `scripts/export_protocol_schema.py`
- 边界测试:`tests/contract/test_protocol_schema_export.py`、`tests/contract/test_sdk_import_boundaries.py`
- Compatibility matrix:`docs/architecture/api/sdk-compatibility-matrix.md`

## 里程碑

- M1:protocol bundle 增加版本号字段与 changelog 出口
- M2:endpoint manifest 与 OpenAPI 3.1 文档实现 breaking-change diff 检测
- M3:protocol 可作为独立制品发布(Phase 5 前提)

## 任务

- [ ] P0 在 schema bundle 输出中增加 `protocol_version` 字段与 changelog 段落(Req: `requirements.md#req-7`)
- [ ] P1 实现 protocol schema diff 工具,CI 中检测对外字段的 breaking change(Req: `requirements.md#req-7`)
- [ ] P1 把 semantic rules 集中维护到独立文件,避免散落在 protocol model 注释中(Req: `requirements.md#req-7`)
- [ ] P2 设计 protocol 独立版本化方案 ADR,放 `docs/architecture/decisions/`(Req: `requirements.md#req-7`)

## 决策 & 争议点

- [ ] protocol 独立制品发布形式:子目录拆包 vs 独立仓库 vs 协议 manifest 文件

## 参考

- `docs/architecture/overview/roadmap.md` Phase 1 / Phase 5
- `docs/architecture/api/sdk-public-surface.md`
- `docs/architecture/api/sdk-compatibility-matrix.md`
