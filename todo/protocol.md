# Protocol TODO

对应需求:`requirements.md#req-4`、`requirements.md#req-7`

## 目标

- 让 `anyagent.protocol.*` 与 schema bundle 成为对外可承诺兼容性的协议真源。

## 当前状态

- 已完成条目已清理;历史记录请查看 Git。本模块当前无未完成任务。
- 已实现能力的长期口径见架构文档:
  - protocol 语义规则集中维护:`docs/architecture/protocol-semantic-rules.md`
  - protocol 版本化 / schema diff / 制品发布形态决策:`docs/architecture/decisions/protocol-versioning.md`

## 当前事实

- 协议真源:`packages/anyagent/src/anyagent/protocol/`
- Schema 导出:`packages/anyagent/src/anyagent/protocol/schema_export.py`,脚本 `scripts/export_protocol_schema.py`
- 边界测试:`tests/contract/test_protocol_schema_export.py`、`tests/contract/test_sdk_import_boundaries.py`
- Compatibility matrix:`docs/architecture/api/sdk-compatibility-matrix.md`

## 里程碑

- M1:protocol bundle 增加版本号字段与 changelog 出口 ✅
- M2:endpoint manifest 与 OpenAPI 3.1 文档实现 breaking-change diff 检测 ✅
- M3:protocol 可作为独立制品发布(Phase 5 前提)✅

## 参考

- `docs/architecture/overview/roadmap.md` Phase 1 / Phase 5
- `docs/architecture/api/sdk-public-surface.md`
- `docs/architecture/api/sdk-compatibility-matrix.md`
