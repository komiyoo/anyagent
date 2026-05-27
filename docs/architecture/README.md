# Architecture 文档索引

本目录承载长期维护的系统架构说明：边界、实体、事件语义、交互契约与收敛策略。

子目录：

- `decisions/`：架构决策记录（ADR 风格）
- `engineering/`：工程流程设计（CI、质量门）

推荐阅读顺序：

1) [roadmap.md](roadmap.md)：Phase 1-4 演进路线图
2) [apps-packages-boundary.md](apps-packages-boundary.md)：anyagent vs anyagent-apps 职责边界与安全模型
3) [responses-api-sdk-and-server.md](responses-api-sdk-and-server.md)：SDK + 内置 Server 泳道与模块边界
4) [sdk-public-surface.md](sdk-public-surface.md)：AnyAgent SDK public surface、typed model facade、repo 内引用与验证入口
5) [stateless-agent-service-architecture.md](stateless-agent-service-architecture.md)：无状态服务语义（并发分片、幂等、事件补发）
6) [storage-minimal-design.md](storage-minimal-design.md)：存储最小设计
7) [sandbox-session-filesystem-design.md](sandbox-session-filesystem-design.md)：服务化沙箱会话文件系统设计（热冷分层、跨实例恢复、安全与数据治理）
8) [skills-tool-runtime-interaction.md](skills-tool-runtime-interaction.md)：Skills 与 Tool Runtime 交互合约
9) [agent-server-runtime-entities.md](agent-server-runtime-entities.md)：运行时实体分层
10) [agent-api-client-stage-events.md](agent-api-client-stage-events.md)：Client Stage Events 设计
11) [studio-control-plane-and-observability.md](studio-control-plane-and-observability.md)：Studio 控制面、使用/研发模式、观测指标与 skill 渠道化导入
12) [platform-connectors.md](platform-connectors.md)：平台 connector contract、官方包优先策略与 Lark/Discord/Telegram 当前状态
13) [testing-strategy.md](testing-strategy.md)：测试分层策略与补齐顺序
14) [decisions/README.md](decisions/README.md)：架构决策记录
15) [engineering/README.md](engineering/README.md)：工程流程
