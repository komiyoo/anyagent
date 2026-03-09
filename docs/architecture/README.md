# Architecture 文档索引

本目录承载长期维护的系统架构说明：边界、实体、事件语义、交互契约与收敛策略。

子目录：

- `decisions/`：架构决策记录（ADR 风格）
- `engineering/`：工程流程设计（CI、质量门）

推荐阅读顺序：

1) [roadmap.md](roadmap.md)：Phase 1-4 演进路线图
2) [apps-packages-boundary.md](apps-packages-boundary.md)：anyagent vs anyagent-apps 职责边界与安全模型
3) [responses-api-sdk-and-server.md](responses-api-sdk-and-server.md)：SDK + 内置 Server 泳道与模块边界
4) [stateless-agent-service-architecture.md](stateless-agent-service-architecture.md)：无状态服务语义（并发分片、幂等、事件补发）
5) [storage-minimal-design.md](storage-minimal-design.md)：存储最小设计
6) [skills-tool-runtime-interaction.md](skills-tool-runtime-interaction.md)：Skills 与 Tool Runtime 交互合约
7) [agent-server-runtime-entities.md](agent-server-runtime-entities.md)：运行时实体分层
8) [agent-api-client-stage-events.md](agent-api-client-stage-events.md)：Client Stage Events 设计
9) [decisions/README.md](decisions/README.md)：架构决策记录
10) [engineering/README.md](engineering/README.md)：工程流程
