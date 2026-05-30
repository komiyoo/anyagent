# Persistence TODO

对应需求:`requirements.md#req-5-13`、`requirements.md#req-3-1`

## 目标

- 让 anyagent 的完整执行过程（prompt 组装、模型调用、工具执行、状态流转）在 event store 中具备全量回放能力,支撑 Studio 历史回看、Eval/Replay、审计合规与生产调试。

## 当前状态

- M1-M4（含 SDK / Studio 行）的已完成条目已清理;历史记录请查看 Git。本模块当前无未完成任务。
- 已实现能力的长期口径见架构文档:
  - 三类 replay（Prompt Context / Tool Execution / Model Request）+ Unified Observability Sink:`docs/architecture/control-plane/studio-control-plane-and-observability.md`
  - replay 截断 / 脱敏 / retention 决策:`docs/architecture/decisions/observability-replay-sink-and-retention.md`

## 当前事实

- Event Store 基础设施已就绪：in-memory / SQLite / PG adapter 均支持 append + query by response_id
- Stage Events 已覆盖：prompt context audit、model stream、tool planned/result、command planned/result、done
- Session Snapshot 存储 `PromptContextAudit`（元数据摘要）,不含渲染文本
- `/internal/prompt/bundle` 可实时预览组装后的完整上下文,但无法回看历史
- `RenderedPromptFragment` 模型已定义,在内存中生成后未持久化

## 设计原则

- **Event Store 优先**：新增持久化数据以 stage event 形式写入 event store,不膨胀 session snapshot
- **Additive-only**：新增 event type,不修改现有 event 的 schema
- **可选写入**：大体积 event（rendered context、full model payload）通过 workspace config 控制是否持久化
- **Graceful fallback**：查询 API 对缺失数据返回降级结果（audit-only）,不报错

## 里程碑

- M1：Prompt Context Replay — rendered fragments 持久化 + 历史查询 API + Studio 展示 ✅
- M2：Tool Execution Replay — tool input/output full payload 持久化 + 查询 ✅
- M3：Model Request Replay — 完整 model request body（applied_body）持久化 + replay ✅
- M4：Unified Observability Sink — 统一 envelope 出口,可对接外部审计/OTel ✅

## 参考

- `docs/architecture/overview/roadmap.md` Phase 1.5 / Phase 2
- `packages/anyagent/src/anyagent/protocol/prompt_context.py` — RenderedPromptFragment 模型
- `packages/anyagent/src/anyagent/protocol/stage_events.py` — 现有 stage event 定义
- `packages/anyagent/src/anyagent/server/response_persistence.py` — 现有持久化上下文
- `packages/anyagent/src/anyagent/server/app.py` L949-1034 — `/internal/prompt/bundle` 参考实现
