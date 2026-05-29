# Persistence TODO

对应需求:`requirements.md#req-5-13`、`requirements.md#req-3-1`

## 目标

- 让 anyagent 的完整执行过程（prompt 组装、模型调用、工具执行、状态流转）在 event store 中具备全量回放能力,支撑 Studio 历史回看、Eval/Replay、审计合规与生产调试。

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

- M1：Prompt Context Replay — rendered fragments 持久化 + 历史查询 API + Studio 展示
- M2：Tool Execution Replay — tool input/output full payload 持久化 + 查询
- M3：Model Request Replay — 完整 model request body（applied_body）持久化 + replay
- M4：Unified Observability Sink — 统一 envelope 出口,可对接外部审计/OTel

## 任务

### M1 — Prompt Context Replay（P0）

- [x] P0 Protocol: 新增 `AnyAgentPromptContextRenderedEvent` stage event 类型,载体为 `list[RenderedPromptFragment]` + `total_chars` + `prompt_cache_key`（Req: `requirements.md#req-5-13`；Impl: `packages/anyagent/src/anyagent/protocol/stage_events.py:258`, `packages/anyagent/src/anyagent/protocol/agent_api_internal.py:130`；Module: `anyagent.protocol.stage_events`, `anyagent.protocol.agent_api_internal`）
- [x] P0 Storage: 在 `ResponsePersistenceContext` 新增 `append_prompt_context_rendered_event_best_effort()`,紧跟现有 audit event 之后调用（Req: `requirements.md#req-5-13`；Impl: `packages/anyagent/src/anyagent/server/response_persistence.py:100`, `packages/anyagent/src/anyagent/server/response_execution.py:67`；Module: `anyagent.server.response_persistence`, `anyagent.server.response_execution`）
- [x] P0 Server: 新增 `GET /internal/responses/{response_id}/prompt-context` API,从 event store 查询 rendered event 并返回（Req: `requirements.md#req-5-13`；Impl: `packages/anyagent/src/anyagent/server/app.py:798`, `packages/anyagent/src/anyagent/server/app.py:1228`；Module: `anyagent.server.app`）
- [ ] P1 SDK: Python client 新增 `get_response_prompt_context()` 方法;TypeScript SDK 同步（Req: `requirements.md#req-5-13`）
- [ ] P1 Studio: 消息 turn 旁加「查看上下文」入口,调用 API 展示 rendered fragments（Req: `requirements.md#req-5-13`）
- [ ] P2 Config: workspace config 增加 `observability.persist_rendered_context` 开关（默认 true）与 `observability.rendered_context_max_bytes` 截断阈值（Req: `requirements.md#req-5-13`）

### M2 — Tool Execution Replay（P1）

- [ ] P1 Protocol: 新增 `AnyAgentToolExecutionDetailEvent` stage event,存储 tool input/output full payload + timing（Req: `requirements.md#req-5-13`）
- [ ] P1 Storage: tool_planned/tool_result 现有事件保持不变;detail event 作为补充,按需持久化完整 payload（Req: `requirements.md#req-5-13`）
- [ ] P1 Server: 新增 `GET /internal/responses/{response_id}/tool-executions` API（Req: `requirements.md#req-5-13`）
- [ ] P2 Studio: tool call card 增加「查看完整输入/输出」展开面板（Req: `requirements.md#req-5-13`）

### M3 — Model Request Replay（P1）

- [ ] P1 Protocol: 新增 `AnyAgentModelRequestEvent` stage event,存储 applied_body（注入 system/developer prompt 后的完整请求体）（Req: `requirements.md#req-5-13`）
- [ ] P1 Storage: 在 model stream 开始前持久化,与 prompt context rendered event 互补（一个存 fragments,一个存最终 body）（Req: `requirements.md#req-5-13`）
- [ ] P1 Server: 新增 `GET /internal/responses/{response_id}/model-request` API（Req: `requirements.md#req-5-13`）
- [ ] P2 Studio: 在 observability 面板增加「模型请求回放」视图（Req: `requirements.md#req-5-13`）

### M4 — Unified Observability Sink（P2）

- [ ] P2 设计统一 observability envelope 出口格式,支持 OTel / 外部审计系统对接（Req: `requirements.md#req-5-13`）
- [ ] P2 实装至少一个 sink adapter（stdout JSON / file / OTel exporter）（Req: `requirements.md#req-5-13`）
- [ ] P2 Event Store 增加 TTL / retention policy,控制大体积 replay event 的生命周期（Req: `requirements.md#req-3-1`）

## 决策 & 争议点

- [ ] rendered context event 的截断策略：按 fragment 截断 vs 按总体积截断
- [ ] model request event 是否需要脱敏（去除 credential ref 等）
- [ ] replay event 的 retention：与 audit event 同生命周期 vs 独立 TTL
- [ ] M4 sink 选型：OTel 直接对接 vs 仓内中间层 + 多 sink 适配（同 server-runtime.md 决策点）

## 参考

- `docs/architecture/overview/roadmap.md` Phase 1.5 / Phase 2
- `packages/anyagent/src/anyagent/protocol/prompt_context.py` — RenderedPromptFragment 模型
- `packages/anyagent/src/anyagent/protocol/stage_events.py` — 现有 stage event 定义
- `packages/anyagent/src/anyagent/server/response_persistence.py` — 现有持久化上下文
- `packages/anyagent/src/anyagent/server/app.py` L949-1034 — `/internal/prompt/bundle` 参考实现
