# Architecture 文档索引

本目录承载“长期维护”的系统架构说明：边界、实体、事件语义、交互契约与收敛策略。

推荐阅读顺序（从全局到局部）：

1) [stateless-agent-service-architecture.md](stateless-agent-service-architecture.md)：无状态服务语义（并发分片、幂等、事件补发、慢消费者治理）
2) [storage-minimal-design.md](storage-minimal-design.md)：存储最小设计（Session/Run/Event/Dedupe/Lock）
3) [responses-api-sdk-and-server.md](responses-api-sdk-and-server.md)：SDK 与服务侧的对齐（泳道视角与模块边界）
4) [skills-tool-runtime-interaction.md](skills-tool-runtime-interaction.md)：Skills 与 Tool Runtime 的交互与协议边界
5) [agent-server-runtime-entities.md](agent-server-runtime-entities.md)：运行时实体分层（命名/职责/边界）
6) [agent-api-client-stage-events.md](agent-api-client-stage-events.md)：Client 阶段性事件（tool/command 粒度）
7) [apps-packages-boundary.md](apps-packages-boundary.md)：`apps/*` vs `packages/*` 的职责边界与收敛策略

约定：

- 新增架构文档时，优先放在最贴近其“职责边界”的目录（避免 `docs/` 根目录堆叠），并更新本 `README.md`。
