# 2026 plans

Execution plans minted this year. Day folders use `MM-DD`. Durable design docs are not stored here.

# This layer

- [2026-09-06 / pydantic-ai loop 与 Langfuse 跟踪](09-06/pydantic-ai-loop-与-langfuse-跟踪-c6cf.md) — 托管面不变，loop 换 pydantic-ai；SDK 跟踪仍走 Event Store，Langfuse OTLP 可选。
- [2026-09-07 / Scripted Reply 扩展点与 connector 回复节奏](09-07/scripted-reply-扩展点与-connector-回复节奏-614d.md) — loop 之前的确定性回复扩展点，命中即合成正常 Response 跳过模型；connector 补回复节奏下限与 typing indicator。

<!-- plan-index:begin -->
- [pydantic-ai loop 与 Langfuse 跟踪](./09-06/pydantic-ai-loop-与-langfuse-跟踪-c6cf.md) — 托管面不变，把 run_tool_loop_* 换成 pydantic-ai，OTLP 接到 Langfuse。
- [Scripted Reply 扩展点与 connector 回复节奏](./09-07/scripted-reply-扩展点与-connector-回复节奏-614d.md) — 在 /v1/responses 进入 loop 前增加 scripted reply 扩展点，命中即合成正常 Response 跳过模型；connector 侧补回复节奏下限与 typing indicator。
- [Chatwoot quick prompt 透传与 SDK 0.4.28 发布](./09-23/00-chatwoot-quick-prompt-透传与-sdk-0.4.28-发布.md) — 修复 Chatwoot quick prompt 字段透传，发布 Python SDK 并升级业务消费侧。
<!-- plan-index:end -->

# Parent

* [plans](../README.md) — dated execution plans.
