# Docs 目录结构（约定）

本仓库的 `docs/` 同时承载两类内容：

1) **长期维护文档**（对外/对内的“稳定说明”）：用于描述协议、架构、安全、验收、性能基线等。
2) **研发辅助文档**（TODO / Draft / WIP / 过程笔记）：用于研发阶段对齐方案与沉淀中间过程，研发完成后可能会迁移到归档或删除。

入口（从这里开始）：

- [acceptance/README.md](acceptance/README.md)：验收与可复现手册（优先读）
- [architecture/README.md](architecture/README.md)：核心架构与关键交互
- [security/README.md](security/README.md)：威胁模型、安全边界、审计留痕、凭证管理
- [performance/load-testing-baseline.md](performance/load-testing-baseline.md)：性能基线与指标口径
- [_dev/README.md](_dev/README.md)：研发草案的“生命周期”与写作约定
- [_notes/README.md](_notes/README.md)：第三方/个人调研笔记（非 SSOT）

为避免平铺式堆叠，`docs/` 按“语义用途”分层：

- `docs/acceptance/`：当前仓库的验收入口说明（SDK-only）；运行型场景验收已迁到同级项目 `../anyagent-apps/docs/acceptance/`
- `docs/security/`：威胁模型、sandbox 安全、tool policy、审计留痕、凭证管理（Credential Vault）
- `docs/architecture/`：总体架构与关键子系统交互（skills/tool-runtime、stateless 语义、存储设计等）
  - `docs/architecture/decisions/`：架构决策记录（ADR，记录取舍和边界）
  - `docs/architecture/engineering/`：工程流程设计（CI、质量门、发布门禁）
  - 运行时实体分层参考：[agent-server-runtime-entities.md](architecture/agent-server-runtime-entities.md)
  - Client 阶段性事件（tool/command 粒度）：[agent-api-client-stage-events.md](architecture/agent-api-client-stage-events.md)
  - apps/packages 职责边界与收敛策略：[apps-packages-boundary.md](architecture/apps-packages-boundary.md)
- `docs/performance/`：压测基线、容量指标口径
- `docs/_dev/`：研发期草案（Draft/WIP/TODO），不保证长期稳定
- `docs/_notes/`：个人/第三方材料与调研笔记（非产品文档）

约束：
- 进度以 `todo/*.md` 为真源；`docs/_dev/` 仅作为研发对齐与沉淀辅助。
- 若 `todo/*.md` 的 `Impl:` 引用到 docs 文件，移动文件后必须同步更新引用路径。

建议：
- 维护/移动文档链接后，跑一次 `python3 scripts/docs/check.py --root .` 做断链与 `Impl:` 证据引用检查。
- 如果你在做“渐进式披露/最小上下文加载”：先跑 `python3 scripts/docs/index.py --root .` 生成 `docs/_manifest.txt`，再用 `python3 scripts/docs/pack.py --tags <topic>` 选出最小文档集。
