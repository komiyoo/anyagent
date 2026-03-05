# Docs 目录结构（约定）

本仓库的 `docs/` 同时承载两类内容：

1) **长期维护文档**（对外/对内的“稳定说明”）：用于描述协议、架构、安全、验收、性能基线等。
2) **研发辅助文档**（TODO / Draft / WIP / 过程笔记）：用于研发阶段对齐方案与沉淀中间过程，研发完成后可能会迁移到归档或删除。

为避免平铺式堆叠，`docs/` 按“语义用途”分层：

- `docs/acceptance/`：验收清单与可复现手册（含 demo 定制化说明 `docs/acceptance/acceptance-demo-customization.md`）
- `docs/security/`：威胁模型、sandbox 安全、tool policy、审计留痕、凭证管理（Credential Vault）
- `docs/architecture/`：总体架构与关键子系统交互（skills/tool-runtime、stateless 语义、存储设计等）
  - 运行时实体分层参考：`docs/architecture/agent-server-runtime-entities.md`
  - Client 阶段性事件（tool/command 粒度）：`docs/architecture/agent-api-client-stage-events.md`
  - apps/packages 职责边界与收敛策略：`docs/architecture/apps-packages-boundary.md`
- `docs/performance/`：压测基线、容量指标口径
- `docs/_dev/`：研发期草案（Draft/WIP/TODO），不保证长期稳定
- `docs/_notes/`：个人/第三方材料与调研笔记（非产品文档）

约束：
- 进度以 `todo/*.md` 为真源；`docs/_dev/` 仅作为研发对齐与沉淀辅助。
- 若 `todo/*.md` 的 `Impl:` 引用到 docs 文件，移动文件后必须同步更新引用路径。
