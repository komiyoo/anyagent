# `_dev/` 草案区约定（非 SSOT）

`docs/_dev/` 用于研发过程中的对齐与沉淀（Draft/WIP）。这里的内容**不保证长期稳定**，也不作为实现真相来源。

## 生命周期（建议）

- 草案开始：在 TODO 中建立条目，并在草案里引用 `Req:`（`requirements.md#req-*`）与 TODO 链接。
- 草案推进：允许快速迭代，但要控制范围，避免把实现细节“永久留在草案里”。
- 草案毕业：提炼到 `docs/architecture|security|acceptance|performance/` 的稳定文档，或直接落到代码/协议模型后删除草案。

## 元信息（推荐）

每个草案文件前 20 行内写清（建议使用 HTML 注释包裹的 YAML 元信息，便于脚本读取且不影响渲染）：

- `Status:` Draft / WIP / Deprecated
- `Expires:` YYYY-MM-DD（到期后要处理：毕业/归档/删除）
- `Graduation:` 目标稳定文档路径（或 TODO 条目）
- `Req:` `requirements.md#req-*`（若关联需求约束）

现有草案：

- `docs/_dev/multi-agent/`：multi-agent 的 WIP 设计与兼容性讨论
