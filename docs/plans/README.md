# Plans

Dated execution plans. Product, architecture, interaction, and data-model facts stay in the durable docs tree; files here only say how to land, in what order, and what to verify.

Layout: `YYYY/MM-DD/<plan-name>-<hex>.md`. Mint files with the `plan-docs` skill script; do not invent paths. Todos use `- [ ]` / `- [x]` / `- [-]`; scan and print sections with `scripts/todos.py`.

# This layer

- [2026](2026/README.md) — 本年执行计划

<!-- plan-index:begin -->
_本区块由 `plan-docs` 的 `scripts/plan-index.py` 从各计划的 frontmatter `depends_on` 派生，不要手改。Wave 按天计算，每天从 Wave 0 起；同一 Wave 内的计划之间没有依赖路径，可以并行；Wave N 依赖 Wave N-1。「当天序号」是计划建当天的建档顺序，跨 Wave 不重置，归档后也保留。_

| Wave | 当天序号 | 计划 | 优先级 | 依赖 |
|---|---|---|---|---|
| 0 | — | [pydantic-ai loop 与 Langfuse 跟踪](./2026/09-06/pydantic-ai-loop-与-langfuse-跟踪-c6cf.md) | — | — |
| 0 | — | [Scripted Reply 扩展点与 connector 回复节奏](./2026/09-07/scripted-reply-扩展点与-connector-回复节奏-614d.md) | — | — |
| 0 | 00 | [Chatwoot quick prompt 透传与 SDK 0.4.28 发布](./2026/09-23/00-chatwoot-quick-prompt-透传与-sdk-0.4.28-发布.md) | — | — |
<!-- plan-index:end -->

# Parent

* [docs/](../README.md) — documentation root.
