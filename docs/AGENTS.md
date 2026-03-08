# docs/ 目录：Agent 文档维护指令

本文件的目的：让 agent 在编辑 `docs/**` 时有**就近**可发现的写作/维护约束，避免文档系统熵增。

## 目标

- 把 `docs/` 当作 agent 的 harness：可导航、可复现、可机械校验。
- 长期维护文档（`docs/acceptance|architecture|security|performance/`）保持稳定、可引用、可验收。
- 研发草案（`docs/_dev/`）可快速迭代，但必须有清晰的“毕业/归档”路径。

## 规则（必须）

- 新增/移动任何 `docs/**.md`：同步更新对应目录的 `README.md`（目录级 TOC）。
- 不把实现真相放在 `docs/_notes/`：需要约束落地时，回写到 `requirements.md` 或长期维护文档。
- 文档里避免重复粘贴协议/字段：以 `requirements.md` 与 `anyagent.protocol.*` 为准，文档只做解释与约束引用。

## 引用格式（推荐统一）

- `docs/**` 内部引用：优先用 **相对路径** Markdown 链接（可点击），例如 `[storage-minimal-design.md](architecture/storage-minimal-design.md)`。
- 仓库根目录（如 `README.md`）引用 docs：用 `docs/...` 形式的仓库相对路径链接，例如 `docs/README.md`。
- “证据引用”（面向可复盘的实现证据）：使用 `path:line`（例如 `../anyagent-apps/apps/agent-api/src/.../app.py:42` 或 `packages/anyagent/src/...:42`），放在反引号里，避免与文档链接混淆。

## YAML 元信息（Front Matter，可选）

当某篇文档会被频繁“按需加载”（例如作为调试/验收/排障的上下文）时，建议在文件顶部增加 YAML front matter，用于**渐进式披露**与快速检索。

渲染提示（避免影响人类阅读）：

- GitHub 原生 Markdown 不识别 front matter，会把 `---` 渲染成分隔线；因此本仓库建议把元信息放在 **HTML 注释**中（机器可读、人类不被打扰）。
- 推荐写法（放在文件最顶部）：
  - `<!--` 换行
  - `---` 起始
  - 若干 `key: value`
  - `---` 结束
  - `-->` 结束

推荐字段（按需填写，不要求齐全）：

- `doc_kind`: `acceptance` | `architecture` | `security` | `performance` | `dev` | `notes`
- `status`: `stable` | `wip` | `draft` | `deprecated`
- `tags`: 字符串数组（用于按主题筛选，例如 `["stateless","idempotency"]`）
- `summary`: 1 句话摘要（用于 context pack 的快速预览）
- `req`: 相关需求锚点数组（例如 `["requirements.md#req-5-13"]`）
- `audience`: `operator` | `developer` | `agent`（可选）

配套工具：

- 生成/刷新 docs manifest（纯文本）：`python3 scripts/docs/index.py --root .`
- 生成/筛选“最小上下文包”：`python3 scripts/docs/pack.py --tags stateless,storage`

## 快速自检（推荐）

- 跑断链与 TODO 证据检查：`python3 scripts/docs/check.py --root .`
- 校验 manifest 覆盖面：`python3 scripts/docs/check.py --root . --check-manifest`

## `docs/_dev/` 草案元信息（推荐）

在草案文件的前 20 行内写清：

- `Status:` Draft / WIP / Deprecated
- `Owner:`（可空，但建议写）
- `Expires:` YYYY-MM-DD（到期后要么毕业到稳定文档，要么归档/删除）
- `Graduation:` 目标稳定文档路径（或 TODO 条目）
- `Req:` `requirements.md#req-*`（若关联需求约束）
