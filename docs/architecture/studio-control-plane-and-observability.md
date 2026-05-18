<!--
---
doc_kind: architecture
status: draft
tags: ["studio", "control-plane", "observability", "skills", "mcp"]
summary: AnyAgent Studio mode split, control-plane toggles, skill channels, and observability contract.
req: ["requirements.md#req-2-1", "requirements.md#req-2-2", "requirements.md#req-4", "requirements.md#req-5-2"]
---
-->

# Studio Control Plane and Observability

本文固定 AnyAgent Studio 下一阶段的控制面与观测面口径。Studio 的页面、交互和生产后端属于 `anyagent-apps`；协议模型、agent 配置语义、skill/MCP/tool enablement、观测事件与 SDK 查询面属于 `anyagent`。

## 1. 模式分层

Studio 左上角 `AnyAgent` logo 区域应成为工作模式切换入口，提供两个模式：

| 模式 | 目标用户 | 主路径 | 侧边栏菜单 |
|---|---|---|---|
| Agent 使用模式 | 运营、销售、交付、非工程使用者 | 选择 agent、运行会话、查看历史与观测、反馈问题 | Home、Agents、Sessions、Observability、Evaluations、Prompts、Settings |
| Agent 研发模式 | agent builder、研发、解决方案工程师 | 创建/配置 agent、调试 prompt/tool/skill/MCP、导入能力、验证变更 | Home、Agents、Configure、Skills、MCP、Tools、Credentials、Debug、Files、Settings |

两种模式都共享当前 workspace、agent selector、连接状态、用户凭据状态。侧边栏折叠/展开是全局 UI 状态，不改变路由语义；折叠时保留图标与 tooltip。

## 2. 观测面归属

数据观测默认放在 Agent 使用模式下的 `Observability`，因为其首要问题是“当前 agent 被真实使用时发生了什么”。研发模式不复制完整页面，而是在 `Debug`、`Configure`、`Skills`、`MCP`、`Tools` 等页面提供跳转与局部摘要，用观测结果驱动 agent 迭代。

`Observability` 至少支持以下粒度：

- 指定 agent 的完整历史记录：按 session、response/run、turn、event 展开。
- 指定 agent 的工具调用观测：tool name、kind、status、latency、error、调用参数摘要、结果摘要、credential/policy 引用摘要。
- 指定 agent 的 MCP 调用观测：server label、transport、tool name、status、latency、error、credential ref。
- 指定 agent 的 skill 查看次数与选择情况：skill stable id、source hash、selected/default-selected、disclosed count、实际引用/触发线索。
- 指定 agent 的轮数统计：session turn count、run count、每轮输入/输出字符长度、平均/分位长度。
- LLM 调用事件统计：model、provider、input tokens、output tokens、cached input tokens、first-token latency、total response latency、finish reason、error。

v0 可以从已有 SSE / internal events / session-run-event store 聚合；Studio 现已补上 `/internal/observability/runs` 作为 agent/session 的 response-run 历史列表入口，并补上 `/internal/observability/summary` 作为单个 response 的 typed telemetry summary 入口，浏览器端优先消费这些摘要，并允许从历史列表选中指定 response/run 后加载对应摘要与事件回放，避免默认扫描大量 raw events。Core 在 run 开始时写入 `anyagent.response.request` 内部事件，并在 summary 中结合 final response 聚合 turn count、总输入/输出字符数与每轮输入/输出字符数。`/internal/observability/runs` 支持 `created_after_ms` / `created_before_ms` / `limit`，Studio 提供 All time / Last hour / Last 24 hours 和 limit 过滤。

## 3. Enable / Disable 配置语义

以下资源都需要支持 enable/disable：

- skills
- MCP servers
- registered/provided tools
- agent-pack source files or config sections

配置真源仍是 agent pack 内文件：`agent.yaml`、`AGENTS.md`、`mcp.json` 和 local `skills/**/SKILL.md`。后台页面可以通过胶囊按钮修改常用开关，同时必须保留源码编辑器作为兜底路径。

建议的配置落点：

| 资源 | 建议字段 | 备注 |
|---|---|---|
| skill | `skills.disabled` 或每个 skill ref 的 `enabled` 派生状态 | default-selected 与 enabled 分开；disabled 的 skill 不参与披露，也不能被设为 default-selected |
| MCP server | `mcpServers.<label>.enabled` | disabled server 不连接、不披露工具、不进入 prompt ref、不读取 credential |
| tool | `tools.disabled_tool_names` 或 policy deny entry | 与 `requested_tool_names` 分开，避免 “requested 但被禁用” 不可解释 |
| file/config section | admin file metadata、Studio editor enablement 或 `agent.yaml` section-level enabled | v0 已在 Studio 源码编辑面提供 Active/Disabled 胶囊控制编辑器状态；配置 section 通过现有 config/MCP 表单控制，不把浏览器直接删除文件作为禁用语义 |

服务端必须在 catalog/detail 响应中返回最终 enablement 摘要与原因，让 Studio 能解释胶囊按钮状态：enabled、disabled、inherited、policy-denied、missing、invalid。

## 4. Skill 导入渠道

`npx skills add` 不能作为唯一抽象。Core admin installer 应升级为渠道化导入：

- `skills.sh`：默认官方/半官方渠道，提交 package/channel/skill/ref，由服务端受限执行并复制到 agent-local skills。
- `github`：按 repo/ref/path 导入，并按来源 ref 检查更新/拉取更新。
- `local_upload`：粘贴或上传 `SKILL.md` 及必要 assets，保持当前本地导入路径。
- `registry`：保留现有 package + skill 的 installer 兼容层，但作为 channel adapter，而不是写死在 UI/协议里。

当前 Core admin installer 已接受 `channel` 字段，`skills.sh` 为默认渠道，`registry` 作为兼容渠道，`github` 支持受限的 `git clone --depth 1 --branch <ref>` 后从 repo 内指定 skill path 复制。导入/安装后的 agent-local skill 会写入 `.anyagent-skill-source.json`，记录 `channel`、`source_ref`、`installed_at`、`source_hash` 等来源元数据。Core admin API 已提供按目录的 update check/apply 入口，更新时按 channel adapter 执行并继续通过 loader 校验 frontmatter、路径边界、文件大小与重复冲突；`local_upload` 因缺少远端来源只返回不可更新原因。

## 5. 后续实现切片

1. Core observability drill-down：在现有 summary/runs 之上继续补服务器端 turn/event 分页与按指标排序。
2. Iteration loop：Studio 已基于 latency、token、tool/MCP 调用数、skill 披露数和 turn 长度生成初版迭代建议并跳转到对应页；后续可把建议持久化为优化任务。
3. Apps Studio page split：Build 模式已提供独立 Skills / MCP / Tools / Files tab，Configure 仍保留总览与常用配置入口。
4. Evaluation handoff：把观测到的高价值 session/run 转成 dataset/evaluation seed。

## 6. 验收要求

- 切换模式不丢失当前 agent、session key、连接配置。
- 折叠侧边栏后所有菜单仍能通过图标和 tooltip 访问。
- 任一 skill/MCP/tool 的胶囊开关保存后，源码文件可见等价变化。
- 任一源码文件手工修改后，表单重新加载能回填或明确进入 invalid/recovery 状态。
- Observability 页面能从一个 response id 追到完整事件历史，并聚合出 token、latency、tool/MCP/skill 指标。
