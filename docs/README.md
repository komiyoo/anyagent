# Docs 目录结构（约定）

本仓库的 `docs/` 同时承载两类内容：

1) **长期维护文档**（对外/对内的“稳定说明”）：用于描述协议、架构、安全、验收、性能基线等。
2) **研发辅助文档**（TODO / Draft / WIP / 过程笔记）：用于研发阶段对齐方案与沉淀中间过程，研发完成后可能会迁移到归档或删除。

为避免平铺式堆叠，`docs/` 按“语义用途”分层：

- `docs/acceptance/`：验收清单与用例（可复现验证）
- `docs/security/`：威胁模型、sandbox 安全、tool policy、审计留痕
- `docs/architecture/`：总体架构与关键子系统交互（skills/tool-runtime、stateless 语义、存储设计等）
- `docs/performance/`：压测基线、容量指标口径
- `docs/_dev/`：研发期草案（Draft/WIP/TODO），不保证长期稳定
- `docs/_notes/`：个人/第三方材料与调研笔记（非产品文档）

约束：
- 进度以 `todo/*.md` 为真源；`docs/_dev/` 仅作为研发对齐与沉淀辅助。
- 若 `todo/*.md` 的 `Impl:` 引用到 docs 文件，移动文件后必须同步更新引用路径。

