# Docs 目录结构

本仓库的 `docs/` 按"语义用途"分层，承载长期维护文档与研发辅助文档。

## 入口（从这里开始）

- [architecture/README.md](architecture/README.md)：核心架构与关键交互
  - [architecture/roadmap.md](architecture/roadmap.md)：Phase 1-4 演进路线图
  - [architecture/apps-packages-boundary.md](architecture/apps-packages-boundary.md)：anyagent vs anyagent-apps 职责边界
  - [architecture/responses-api-sdk-and-server.md](architecture/responses-api-sdk-and-server.md)：SDK + Server 泳道与模块边界
- [security/README.md](security/README.md)：威胁模型、安全边界、审计留痕、凭证管理
- [acceptance/README.md](acceptance/README.md)：验收与可复现手册
- [performance/load-testing-baseline.md](performance/load-testing-baseline.md)：性能基线

## 目录结构

- `docs/architecture/` — 架构设计（长期维护）
  - `docs/architecture/decisions/` — 架构决策记录（ADR）
  - `docs/architecture/engineering/` — 工程流程（CI、质量门）
- `docs/security/` — 安全设计（威胁模型、sandbox、tool policy、credential vault）
- `docs/acceptance/` — 验收入口
- `docs/performance/` — 性能基线
- `docs/_dev/` — 研发草案（Draft/WIP，不保证长期稳定）
- `docs/_notes/` — 第三方/个人调研笔记（非 SSOT）

## 约定

- 进度以 `todo/*.md` 为真源
- 新增文档优先放在最贴近其"职责边界"的目录
- 维护/移动文档后，跑 `python3 scripts/docs/check.py --root .` 检查断链
