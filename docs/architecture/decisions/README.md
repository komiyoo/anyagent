# Architecture Decisions（ADR 索引）

本目录用于沉淀“已经做出的架构决策”，强调：

- 为什么这么做（约束/目标）
- 不这么做会有什么代价
- 当前实现边界和兼容口径

当前决策：

1. [openai-first-api-surface.md](openai-first-api-surface.md)：对外接口以 OpenAI Responses API 为主，AnyAgent Client SDK 以单一 `AnyAgent` 入口 + `client.openai/client.async_openai` 主路径 + `responses`/`events`/`skills` 超集命名空间作为收敛方案。
2. [skills-selection-policy.md](skills-selection-policy.md)：skills 选择策略（显式优先、隐式默认关闭）。
3. [tool-runtime-federation-v0.md](tool-runtime-federation-v0.md)：Tool Runtime 联邦边界、热更新控制面与 Admin API 形态。
4. [single-repo-multi-package-boundary.md](single-repo-multi-package-boundary.md)：保持单仓库协作，通过协议真源、多包边界和 contract tests 支撑 server/client/studio 与多语言 SDK，暂不拆独立 repo。
5. [sandbox-backend-selection.md](sandbox-backend-selection.md)：第二 sandbox backend 选定 OpenSandbox on Kubernetes，`local-unsafe` 仅作为本地 reference/dev backend。
6. [run-scheduling-lock-contract.md](run-scheduling-lock-contract.md)：跨节点 Run 调度以 `session_partition_key` 为 keyed serialization 边界，锁统一为可续租 LeaseLock contract，并要求 Redis/PostgreSQL adapter 共享语义。
7. [plugin-connector-contract-v1.md](plugin-connector-contract-v1.md)：Plugin / Connector 采用统一 manifest schema，并用 capability matrix 区分 Gateway 与 Tool Runtime 的 host 能力面。

维护约定：

- 新增 ADR 时，命名建议 `<topic>.md`，并补充 `Status/Date/Req/Scope`。
- ADR 只记录已接受的架构决策、约束和事实；任务状态和执行记录放在对应 `todo/*.md`。
