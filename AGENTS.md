# anyagent：AI Agent 自动化研发行为规范（Agent-Naive / SSOT / 可观测 / 可重放）

本文件 `AGENTS.md` 的定位：**指导 AI Agent 在本仓库进行自动化研发的行为规范**（不是产品文档、不是需求文档、也不是“代码之外的第二套真相”）

本仓库刻意按 **Agentic Engineering** 方式组织：让“第一次打开仓库的 agent / 工程师”也能稳定地定位、实现、验证、复盘；并能把改动沉淀为可复用的能力（compound engineering）

理念参考：`docs/_notes/third-party/wx/agent_design_metting.md`（上下文工程 / 验证闭环 / 工具化 / Agentic codebase / 复合式工程）。

---

## 0) 首要职责

- 首要责任是 **项目长期可维护性** 与 **未来用户（人类 + agent）的体验**，而不是“只把当前需求凑合做完”
- 任何非平凡改动都要先做上下文收集与约束对齐（`requirements.md` / `todo/` / `docs/architecture|security|acceptance/`），再落地实现
- 如果任务本身不够明确：优先把它变得可实现（补 `todo/*` 的 `[needs-design]` 决策点、补需求锚点、补验收方式），而不是盲目写代码

---

## 1) 首条消息 / 任务不明确时怎么做（Agent-Naive Quickstart）

当用户没有给出明确文件路径或具体目标时，按下面顺序行动（尽量并行）：

1. 阅读 `README.md`（文档索引）与相关模块 README（例如 `apps/agent-api/README.md`、`apps/tool-runtime/README.md`）。
2. 运行进度定位脚本：`python3 scripts/anyagent_progress.py --root .`，找出“下一条 TODO（file:line）”。
3. 从 `todo/*.md` 定位任务条目，再回溯到 `requirements.md#req-*` 找稳定约束。
4. 仍不清晰时：向用户追问**要改哪个模块**（agent-api / tool-runtime / gateway / storage / multi-agent / skills-disclosure / security / acceptance），并建议把任务落在对应 `todo/<module>.md`（带 `Req:`）。

---

## 2) 单一真源（SSOT）地图

- **需求真源（What/Why）**：`requirements.md`（用 `requirements.md#req-*` 稳定锚点引用）
- **任务真源（When/Who/Progress）**：`todo/*.md`（按文件内顺序推进；完成时必须补 `Impl/Module` 证据）
- **行为真源（How/Truth）**：代码（`apps/`、`packages/`）。文档不能“改写代码事实”，只能解释或约束。
- **长期维护文档（How/Contract）**：`docs/architecture|security|acceptance|performance/`
- **研发草案与笔记（非稳定）**：`docs/_dev/`、`docs/_notes/`（不能作为实现完成证据，除非 TODO 明确允许）

---

### 公共抽象约束（新增）

- **外部接口策略（OpenAI First + 资源型命名空间 SDK）**：
  - 对外 API 的主契约以 OpenAI Responses API + OpenAI 官方 SDK 兼容为第一优先级。
  - `packages/anyagent` 的 Client SDK 以 `AnyAgent` 入口类 + 资源型命名空间模式（`client.responses.*` / `client.events.*` / `client.skills.*`）承载超集能力，`responses` 委托 OpenAI 官方 SDK，不重复封装。不采用 local orchestration 模式。
  - 设计决策：`docs/architecture/decisions/openai-first-api-surface.md`。
- **层级化组织（禁止平铺）**：
  - 代码与文档新增内容必须按“功能/模块/领域”分层落目录；禁止把同类文件持续平铺到单一目录根层。
  - 新增子目录后必须补该目录 `README.md`（目录级 TOC），并把入口挂到上一级 TOC。
- **CI 质量门（默认要求）**：
  - 变更应至少通过“文档护栏 + 离线 smoke”两层 gate（可在 `.github/workflows/ci.yml` 与 `scripts/ci/*` 落地）。
  - 在线验收（依赖外部密钥/服务）可以作为可选 gate，不得替代离线基础 gate。

---

### 文档系统（Docs as Harness）

本仓库把“文档 + 约束 + 验收脚本”视为 agent 的 **harness**（操作系统的一部分）：就近可发现、可维护、可机械校验。

- `docs/README.md` 是 `docs/` 的结构约定；每个子目录都应有自己的 `README.md` 作为 **目录级 TOC**（减少“平铺式堆叠”与检索噪音）。
- **长期维护文档**（`docs/acceptance|security|architecture|performance/`）必须能被 TOC 找到；新增/移动文档时同步更新对应目录 `README.md`。
- **研发草案**（`docs/_dev/`）需要显式标注状态与“毕业条件”；完成后应迁移/提炼到长期维护文档或删除归档，避免熵持续累积。
- **第三方/个人笔记**（`docs/_notes/`）用于调研与启发，不作为产品/实现真相来源；需要落地的约束必须回写到 `requirements.md` 或对应长期维护文档。
- 维护文档引用一致性：移动/重命名 docs 后，优先跑 `python3 scripts/docs/check.py --root .`，修复断链与 TODO 的 `Impl:` 证据引用。
- 渐进式披露：用 `python3 scripts/docs/pack.py --tags <topic>` 先筛出“最小文档上下文列表”，再按需打开对应文档，避免一次性加载过多无关上下文。

设计参考（第三方摘要）：`docs/_notes/third-party/openai/harness-engineering.md`。

## 3) 一等公民概念（First-Class Concepts）

这些概念用于 **链路可观测性** 与 **可重放（replay）**，也是你在实现/排障/验收时必须对齐的术语。

### 标识与关联键（Correlation Keys）

- `agent_id`：同一套服务内不同 agent 的稳定标识（persona/权限/skills/tool policy 组合）。
- `session_key`：外部平台线程/会话键（跨请求稳定）。
- `session_partition_key`：并发分片键，建议固定为 `"{agent_id}::{session_key}"`。
- `response_id` / `run_id`：一次 `POST /v1/responses` 的执行实例标识（本仓库多处把 `response_id` 作为 `run_id` 使用）。
- `idempotency_key`：幂等去重键（请求级或 tool-call 级），用于重试不触发重复执行。
- `tool_call_id`：单次工具调用的稳定标识（来自模型/协议事件）。
- `tool_name`：工具全名（如 `core.web_search`、`feishu.doc.create`）。
- `trace_id` / `span_id`：跨服务链路追踪字段（若有，则必须贯穿到日志/审计字段里）。
- `audit_ref`：一次 tool 调用的稳定审计引用（用于把执行日志与外部审计表/采样系统关联）。
- `seq`：run 内事件序号（单调递增），用于断线重连与事件补发/重放。

参考实现与约束：

- `requirements.md#req-5-9`（`context.trace` 结构）
- `requirements.md#req-5-13`、`docs/security/audit-logging.md`（审计与留痕字段）
- `docs/architecture/stateless-agent-service-architecture.md`（`Event`、`seq`、reconnect/replay 语义）
- `docs/architecture/storage-minimal-design.md`（Run/Event Store 最小 schema）

### 产物与引用

任何“可复盘”的东西都应当能被引用到：

- **代码证据**：`path:line`（用于 TODO 的 `Impl:` 字段）
- **可复现命令**：一条或多条可直接执行的命令（带必要 env）
- **输入快照**：触发问题/需求的最小请求体（脱敏后）
- **输出/事件**：关键事件类型 + `response_id/run_id` + `last_seq`（无需贴全量日志）

本地临时产物（可能含敏感信息）默认放在 gitignore 的目录中：

- `.runs/`：本地 run/replay 相关临时文件（日志片段、请求快照、事件摘录等）
- `.cloud/`：可选的“第二大脑”（不适合提交到仓库但又希望被 agent 复用的材料）

若要把材料作为长期可追溯证据：必须脱敏后放入 `docs/acceptance/` 或对应模块文档，并在 TODO 中引用。

---

## 4) Agent 自观测链（Observability Chain）与 Replay 约束

目标：任何线上/本地问题都能沿着“输入 -> run -> 事件 -> 工具 -> 持久化”串起来，并且能重放。

### 最小观测闭环（必须做到）

- **每次工具执行都可追踪**：Tool Runtime 在 `tool_execute.begin|done|cache_hit` 日志中输出结构化字段（见 `docs/security/audit-logging.md`）。
- **事件可重放**：run 内事件必须有 `seq` 单调递增；断线重连使用 `last_seq` 补发（见 `docs/architecture/stateless-agent-service-architecture.md`）。
- **幂等可解释**：命中幂等去重时必须能说明“命中的是哪个键、对应哪个 run/tool_call”（不要默默吞掉）。
- **敏感信息不落盘**：禁止把 token、原始 `arguments_json`、原始工具输出写进日志（必要时只写摘要 + `audit_ref`）。

### 提示友好（Prompt-Friendly）输出约定

当你（agent）在仓库里交付改动或排障结论时，默认按下面格式输出信息，减少追问成本：

- **结论一句话**：改了什么 / 修了什么 / 现在是什么语义
- **证据链**：`requirements.md#req-*` + `todo/<module>.md` + `Impl: path:line`
- **如何复现**：最小命令 + 必要 env（不含 secret；secret 用占位符）
- **如何验证**：最小验收脚本/接口调用（优先使用 `docs/acceptance/` 给出的步骤）

---

## 5) 标准工作流（从想法到交付，必须执行）

### 快速定位（推荐第一步）

- `python3 scripts/anyagent_progress.py --root .`
  - 展示每个模块 TODO 的“连续完成数”和“下一条 TODO（第几条 + file:line）”
  - 若提示 `done_missing_evidence`，必须先补齐 `Impl/Module` 再继续推进
- 只有在你确实需要“扫实现线索”时才用：
  - `python3 scripts/anyagent_progress.py --root . --scan-impl`
  - `--include-md` 仅用于“文档线索”，不能等价于“已实现”

### 需求与任务对齐（必须）

- 在 `requirements.md` 找到对应章节（用 `req-*` 锚点引用）。
- 在 `todo/` 选择正确模块文件新增/更新任务（不确定先放 `todo/backlog.md`）。
- 任务行建议格式：`- [ ] P0/P1/P2 <任务>（Req: requirements.md#req-*）`

### 实现（code as SSOT）

- 先改代码，再让文档与 TODO 引用代码事实（避免“文档先行、实现漂移”）。
- 避免重复实现与旁路：同一规则/策略/枚举必须保持单一真源。
- 对外协议/字段：以 `requirements.md` + `anyagent.protocol.*` 为准，禁止在多个位置各写一份“自己的协议解释”。
- **协议优先（Protocol-First）**：新增/修改任何“可被其他模块消费”的协议或事件（外部 API、内部 `/internal/*`、SSE 事件、tool/runtime payload 等）时，必须先在 `anyagent.protocol.*` 定义/更新数据模型（Pydantic），再实现具体功能；server/client 必须复用同一份模型，禁止两边各自手写 `dict` shape 造成漂移。
- **SDK/示例强类型（Typed-by-Default）**：任何 SDK（尤其 `packages/anyagent`）与示例项目都必须有完备的类型/协议系统支撑：对外输入/输出/事件必须有明确的 typed model（优先 `anyagent.protocol.*` 的 Pydantic 模型或 OpenAI 官方 SDK typed models）；示例代码必须使用这些类型完成解析/校验/构造，禁止“直接拼 `dict`/随手 json.loads 后到处传”导致协议漂移与不可维护。
- 对外兼容面（Responses / Tool Runtime）：优先以 **协议模型** 与 **可观测字段** 为中心组织实现，确保 replay 与排障不靠猜。

### 实现后同步 TODO（必须）

完成某条任务后，立刻在对应 `todo/<module>.md`：

- 勾选为完成：`- [x] ...`
- 同一行补齐证据字段：`Impl: <path:line>；Module: <module>`
- 若涉及多文件：TODO 行只写**主入口**的 `Impl:`，其余放到下一行 `- refs:` 小列表

### 验证与验收（必须）

优先选择“最小且可复现”的验证：

- 文档化验收：`docs/acceptance/acceptance-*.md`
- Responses API 基本 smoke：`tests/acceptance/openai/acceptance_openai_sdk_smoke.py`（见 `docs/acceptance/acceptance-responses-api.md`）
- HTTP 直连 smoke（不依赖 OpenAI SDK）：`tests/acceptance/agent_api/acceptance_responses_smoke.py`
- 本地启动（Python + uv）：
  - `cd apps/tool-runtime && uv sync && TOOL_RUNTIME_INTERNAL_KEY=... uv run tool-runtime`
  - `cd apps/agent-api && uv sync && uv run agent-api`

无法在仓库内自动验证时：必须在说明里写清“原因 + 可复现命令/步骤”。

---

## 6) 工具与工程纪律（可执行规则）

### 工具调用与并行（适用于自动化研发）

- 优先并行做“读/搜/定位”类操作（减少轮次）；输出要可读、可复盘（不要倾倒超长日志）。
- 长时间运行任务（起服务、跑验收、build）必须使用会话模式（避免卡住主流程）。

### Git 安全规则（防止破坏并行工作）

- **允许破坏性调整**：默认不做兼容层/兼容 shim，只保留“唯一、当前、最自然”的实现；允许删除/移动旧路径以维持单一真源（SSOT），除非用户明确要求保留兼容。
- 不要重写历史，不要做不可恢复的工作区清理。
- 禁止破坏性命令：`git reset --hard`、`git checkout .`、`git clean -fd`、`git stash`。
- staged 变更必须可控：不要用 `git add -A` / `git add .`；只 `git add <你本次改动的文件>`。
- 任何需要 `git push` 的动作：必须先征求用户同意。

### 依赖与供应链

- Python 依赖统一用 `uv` + `pyproject.toml` 管理；不要“临时 pip 安装”污染环境。
- 没有充分理由不要新增依赖；若必须新增，先说明动机与风险（体积、维护、CVE）。
- 允许用 `uv run --with openai` 临时安装 OpenAI SDK 做验收（不修改 lock），见 `docs/acceptance/acceptance-responses-api.md`。

---

## 7) Codex/Agent 友好开发约定（让 agent 更快、更稳）

- **先搜后读**：优先 `rg`/`git grep` 定位入口；大文件先抽“语义骨架”（函数/类/协议定义）再读实现。
- **避免上下文污染**：不要把整文件/大段日志贴进对话；用摘要 + `path:line` + 可复现命令替代。
- **输出结构化信息**：日志/错误尽量结构化；协议错误必须可机读（见 `requirements.md` 中 Tool Runtime 错误结构约束）。
- **安全默认**：任何外部输入都要校验；任何可能含敏感信息的输出都要脱敏与限长。
- **不泄露 secrets**：不要把 `.env`、token、私钥、cookie、平台回调 payload 原文贴进对话/日志；必要时仅贴“字段名 + 摘要 + `audit_ref`/`trace_id`”。
- **代码质量（必须）**：
  - 优先写“强 primitives + 清晰边界”，避免为了“看起来能跑”引入临时旁路。
  - 结构化数据优先用 `pydantic` 模型/Typed 结构表达，避免到处散落 `dict[str, Any]`。
  - 不要凭记忆“编协议/编 SDK 字段”：以 `requirements.md`、官方 SDK/类型定义、以及仓库内 `anyagent.protocol.*` 为准。
  - 错误处理要显式且可机读：避免吞异常或返回不可解析的字符串错误。
  - **Docstring 约束（必须）**：新增/修改对外可见（public）的 `module/class/function/method` 必须写 docstring，且**第一行必须是单句摘要**（用于自动“功能披露/调用链说明”）；必要时补 `Args/Returns/Raises`。

---

## 8) Definition of Done（完成标准）

- `todo/` 中对应任务已勾选，并保留 `Req: requirements.md#req-*`。
- TODO 行包含 `Impl: path:line；Module: ...` 证据字段。
- 有最小验证闭环（命令/验收文档/接口调用三选一，优先可自动化）。
- 若涉及可观测性/重放相关变更：明确说明影响到哪些关联键（`trace_id/run_id/seq/audit_ref` 等）与兼容性边界。
