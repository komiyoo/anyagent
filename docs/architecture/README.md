# Architecture 文档索引

本目录承载长期维护的系统架构说明：边界、实体、事件语义、交互契约与已实现事实。

## 模块目录

- `overview/`：项目边界、路线图与跨仓职责
- `api/`：OpenAI Responses API、SDK surface、Stage Events 与兼容矩阵
- `runtime/`：Agent Packs、运行时实体、stateless service、sandbox session filesystem
- `tool-runtime/`：Tool Runtime manifest/execute、registry、命名、context、幂等与取消
- `storage/`：Session/Run/Event/Dedupe/Lock 等存储设计
- `skills/`：Skills 动态披露与 Tool Runtime 交互
- `integrations/`：Gateway 平台路由与 connector contract
- `multi-agent/`：Multi-Agent 编排、隔离、事件与 AgentControl
- `control-plane/`：Studio 控制面与观测
- `testing/`：测试分层策略
- `decisions/`：架构决策记录（ADR 风格）
- `engineering/`：工程流程设计（CI、质量门）

## 推荐阅读顺序

1) [overview/apps-packages-boundary.md](overview/apps-packages-boundary.md)：anyagent vs anyagent-apps 职责边界与安全模型
2) [overview/roadmap.md](overview/roadmap.md)：历史演进路线与当前架构锚点
3) [api/responses-api-sdk-and-server.md](api/responses-api-sdk-and-server.md)：SDK + 内置 Server 泳道与模块边界
4) [runtime/agent-packs-and-runtime-config.md](runtime/agent-packs-and-runtime-config.md)：Agent Packs、AGENTS.md 注入、AgentSpec、agent_id 路由与 session runtime config
5) [tool-runtime/tool-runtime-contract.md](tool-runtime/tool-runtime-contract.md)：Tool Runtime manifest/execute、registry、tool naming、context、幂等与取消
6) [runtime/stateless-agent-service-architecture.md](runtime/stateless-agent-service-architecture.md)：无状态服务语义（并发分片、幂等、事件补发）
7) [storage/storage-minimal-design.md](storage/storage-minimal-design.md)：存储最小设计
8) [skills/skills-dynamic-disclosure.md](skills/skills-dynamic-disclosure.md)：Skills 包结构、roots/scope、enable/disable、依赖、权限与动态披露
9) [integrations/gateway-platform-routing.md](integrations/gateway-platform-routing.md)：Gateway 平台消息、session/thread 绑定与多 agent 路由
10) [multi-agent/multi-agent-collaboration.md](multi-agent/multi-agent-collaboration.md)：Multi-Agent 编排工具、隔离、事件与 AgentControl

## 模块文档

### API 与 SDK

- [api/responses-api-sdk-and-server.md](api/responses-api-sdk-and-server.md)：SDK + 内置 Server 泳道与模块边界
- [api/sdk-public-surface.md](api/sdk-public-surface.md)：AnyAgent SDK public surface、typed model facade、repo 内引用与验证入口
- [api/sdk-compatibility-matrix.md](api/sdk-compatibility-matrix.md)：server/protocol/SDK/Studio 兼容矩阵
- [api/agent-api-client-stage-events.md](api/agent-api-client-stage-events.md)：Client Stage Events 设计

### Runtime、Storage 与 Sandbox

- [runtime/agent-packs-and-runtime-config.md](runtime/agent-packs-and-runtime-config.md)：Agent Packs、AGENTS.md 注入、AgentSpec、agent_id 路由与 session runtime config
- [runtime/agent-server-runtime-entities.md](runtime/agent-server-runtime-entities.md)：运行时实体分层
- [runtime/stateless-agent-service-architecture.md](runtime/stateless-agent-service-architecture.md)：无状态服务语义
- [runtime/sandbox-session-filesystem-design.md](runtime/sandbox-session-filesystem-design.md)：服务化沙箱会话文件系统设计
- [storage/storage-minimal-design.md](storage/storage-minimal-design.md)：存储最小设计

### Tool、Skills 与生态

- [tool-runtime/tool-runtime-contract.md](tool-runtime/tool-runtime-contract.md)：Tool Runtime manifest/execute 合约
- [skills/skills-dynamic-disclosure.md](skills/skills-dynamic-disclosure.md)：Skills 动态披露
- [skills/skills-tool-runtime-interaction.md](skills/skills-tool-runtime-interaction.md)：Skills 与 Tool Runtime 交互合约
- [integrations/gateway-platform-routing.md](integrations/gateway-platform-routing.md)：Gateway 平台路由
- [integrations/platform-connectors.md](integrations/platform-connectors.md)：平台 connector contract
- [multi-agent/multi-agent-collaboration.md](multi-agent/multi-agent-collaboration.md)：Multi-Agent 编排

### Control Plane、测试与工程

- [control-plane/studio-control-plane-and-observability.md](control-plane/studio-control-plane-and-observability.md)：Studio 控制面、使用/研发模式、观测指标与 skill 渠道化导入
- [testing/testing-strategy.md](testing/testing-strategy.md)：测试分层策略
- [decisions/README.md](decisions/README.md)：架构决策记录
- [engineering/README.md](engineering/README.md)：工程流程

关键 ADR：

- [decisions/single-repo-multi-package-boundary.md](decisions/single-repo-multi-package-boundary.md)：server/client/studio 保持单仓库协作，通过 protocol/server/SDK/Studio 多包边界和同 repo SDK scaffold 维护兼容。
