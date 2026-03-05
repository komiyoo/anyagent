# Architecture Decisions（ADR 索引）

本目录用于沉淀“已经做出的架构决策”，强调：

- 为什么这么做（约束/目标）
- 不这么做会有什么代价
- 当前阶段（v0/v1/v2）的边界

当前决策：

1. [openai-first-api-surface.md](openai-first-api-surface.md)：对外接口以 OpenAI Responses API 为主，AnyAgent Client SDK 以资源型命名空间模式（`AnyAgent` 入口 + `responses`/`events`/`skills` 子命名空间）作为超集。
2. [skills-selection-policy.md](skills-selection-policy.md)：skills 选择策略（显式优先、隐式默认关闭）。
3. [tool-runtime-federation-v0.md](tool-runtime-federation-v0.md)：Tool Runtime 联邦边界、热更新控制面与 Admin API 形态。

维护约定：

- 新增 ADR 时，命名建议 `<topic>.md`，并补充 `Status/Date/Req/Scope`。
- ADR 的结论必须同步回 `todo/*.md` 的“决策 & 争议点”条目（带 `Impl: path:line`）。
