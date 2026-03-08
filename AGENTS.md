# anyagent：AI Agent 自动化研发行为规范

本文件 `AGENTS.md` 的定位：**指导 AI Agent 在本仓库进行自动化研发的行为规范**（不是产品文档、不是需求文档、也不是"代码之外的第二套真相"）。

核心目标：**一切研发流程可自动化、可自迭代、渐进式探索**。

本仓库按 **Agentic Engineering** 方式组织，围绕五个支柱：上下文工程、验证闭环、工具化、Agentic 代码库、复合式工程（参考 `docs/_notes/third-party/wx/agent_design_metting.md`）。

---

## 0) 首要职责

- 首要责任是 **项目长期可维护性** 与 **未来用户（人类 + agent）的体验**，而不是"只把当前需求凑合做完"
- 任何非平凡改动都要先做上下文收集与约束对齐（`requirements.md` / `todo/` / `docs/architecture|security|acceptance/`），再落地实现
- 如果任务本身不够明确：优先把它变得可实现（补 `todo/*` 的 `[needs-design]` 决策点、补需求锚点、补验收方式），而不是盲目写代码
- **每次改动都要想：这次做的事能否让下一次更快、更稳、更自动？**

---

## 1) 上下文工程（Context Engineering）

输入决定输出。Agent 的上限不是模型参数，而是它所处的信息环境。

### 1.1 Agent-Naive Quickstart（首条消息 / 任务不明确时）

当用户没有给出明确文件路径或具体目标时，按下面顺序行动（尽量并行）：

1. 阅读 `README.md`（文档索引）与相关模块 README（例如 `../anyagent-apps/apps/agent-api/README.md`、`../anyagent-apps/apps/tool-runtime/README.md`）。
2. 运行进度定位脚本：`python3 scripts/anyagent_progress.py --root .`，找出"下一条 TODO（file:line）"。
3. 从 `todo/*.md` 定位任务条目，再回溯到 `requirements.md#req-*` 找稳定约束。
4. 仍不清晰时：向用户追问**要改哪个模块**（agent-api / tool-runtime / gateway / storage / multi-agent / skills-disclosure / security / acceptance），并建议把任务落在对应 `todo/<module>.md`（带 `Req:`）。

### 1.2 SSOT 地图（不重复、不冲突的信息源）

- **需求真源（What/Why）**：`requirements.md`（用 `requirements.md#req-*` 稳定锚点引用）
- **任务真源（When/Who/Progress）**：`todo/*.md`（按文件内顺序推进；完成时必须补 `Impl/Module` 证据）
- **行为真源（How/Truth）**：当前仓库代码以 `packages/` 为主；运行型参考实现位于同级项目 `../anyagent-apps/apps/`。文档不能"改写代码事实"，只能解释或约束
- **长期维护文档（How/Contract）**：`docs/architecture|security|acceptance|performance/`
- **研发草案与笔记（非稳定）**：`docs/_dev/`、`docs/_notes/`（不能作为实现完成证据，除非 TODO 明确允许）
- **第二大脑（.cloud/）**：不适合提交到仓库但又希望被 agent 复用的领域知识（产品规格、配置决策、调研等），默认 gitignore

### 1.3 渐进式披露（避免上下文过载）

- 用 `python3 scripts/docs/pack.py --tags <topic>` 先筛出"最小文档上下文列表"，再按需打开，避免一次性加载过多无关上下文
- **先搜后读**：优先 `rg`/`git grep` 定位入口；大文件先抽"语义骨架"（函数/类/协议定义）再读实现
- **避免上下文污染**：不要把整文件/大段日志贴进对话；用摘要 + `path:line` + 可复现命令替代

### 1.4 文档系统（Docs as Harness）

本仓库把"文档 + 约束 + 验收脚本"视为 agent 的 **harness**（操作系统的一部分）：就近可发现、可维护、可机械校验。

- `docs/README.md` 是 `docs/` 的结构约定；每个子目录都应有自己的 `README.md` 作为 **目录级 TOC**
- **长期维护文档**（`docs/acceptance|security|architecture|performance/`）必须能被 TOC 找到；新增/移动文档时同步更新对应目录 `README.md`
- **研发草案**（`docs/_dev/`）需要显式标注状态与"毕业条件"；完成后应迁移/提炼到长期维护文档或删除归档
- **第三方/个人笔记**（`docs/_notes/`）用于调研与启发，不作为产品/实现真相来源；需要落地的约束必须回写到 `requirements.md` 或对应长期维护文档
- 维护文档引用一致性：移动/重命名 docs 后，优先跑 `python3 scripts/docs/check.py --root .`，修复断链与 TODO 的 `Impl:` 证据引用

参考：`docs/_notes/third-party/openai/harness-engineering.md`。

---

## 2) 验证闭环（Agentic Validation）

没有验证的输出只是概率猜测。Agent 必须能自我验证，而不仅仅是生成。

### 2.1 实现中的自验证（必须）

- **改了就要验**：每次代码改动后，agent 必须主动执行相关验证，而不是等人来跑
- 优先选择"最小且可复现"的验证：
  - 文档化验收：`docs/acceptance/acceptance-*.md`
  - Responses API 基本 smoke：`../anyagent-apps/tests/acceptance/openai/acceptance_openai_sdk_smoke.py`
  - HTTP 直连 smoke（不依赖 OpenAI SDK）：`../anyagent-apps/tests/acceptance/agent_api/acceptance_responses_smoke.py`
  - 本地启动验证：`cd ../anyagent-apps/apps/agent-api && uv sync && uv run agent-api`
- 无法在仓库内自动验证时：必须在说明里写清"原因 + 可复现命令/步骤"

### 2.2 可观测闭环（排障靠数据不靠猜）

目标：任何线上/本地问题都能沿着"输入 → run → 事件 → 工具 → 持久化"串起来，并且能重放。

- **每次工具执行都可追踪**：Tool Runtime 在 `tool_execute.begin|done|cache_hit` 日志中输出结构化字段（见 `docs/security/audit-logging.md`）
- **事件可重放**：run 内事件必须有 `seq` 单调递增；断线重连使用 `last_seq` 补发
- **幂等可解释**：命中幂等去重时必须能说明"命中的是哪个键、对应哪个 run/tool_call"
- **敏感信息不落盘**：禁止把 token、原始 `arguments_json`、原始工具输出写进日志（必要时只写摘要 + `audit_ref`）

### 2.3 交付输出约定（Prompt-Friendly）

当你（agent）在仓库里交付改动或排障结论时，默认按下面格式输出，减少追问成本：

- **结论一句话**：改了什么 / 修了什么 / 现在是什么语义
- **证据链**：`requirements.md#req-*` + `todo/<module>.md` + `Impl: path:line`
- **如何复现**：最小命令 + 必要 env（不含 secret；secret 用占位符）
- **如何验证**：最小验收脚本/接口调用（优先使用 `docs/acceptance/` 给出的步骤）

---

## 3) 工具化（Agentic Tooling）

凡是需要人工干预的地方，都是摩擦。凡是摩擦，都是工具化的机会。

### 3.1 已有工具（优先使用）

- `python3 scripts/anyagent_progress.py --root .` — 进度定位
- `python3 scripts/docs/check.py --root .` — 文档断链检查
- `python3 scripts/docs/pack.py --tags <topic>` — 渐进式上下文筛选
- `python3 scripts/docs/index.py` — docs manifest 生成
- `scripts/ci/run_docs_guardrails.sh` — CI 文档护栏
- `scripts/ci/run_offline_smokes.sh` — CI 离线 smoke

### 3.2 工具化意识（Agent 应主动具备）

- **发现摩擦 → 提议工具化**：如果某个操作在多次任务中重复出现且需要人工干预，agent 应主动提议将其脚本化/工具化，并建议放入 `scripts/`
- **不要手动重复做可自动化的事**：能用脚本跑的验证不要手动跑，能用工具链检查的一致性不要人工比对
- 长时间运行任务（起服务、跑验收、build）必须使用后台模式（避免卡住主流程）

---

## 4) Agentic 代码库（让代码对 Agent 友好）

我们不只是为下一位工程师写代码，也是在为下一位 Agent 写代码。

### 4.1 协议与类型系统

- **协议优先（Protocol-First）**：新增/修改任何"可被其他模块消费"的协议或事件时，必须先在 `anyagent.protocol.*` 定义/更新数据模型（Pydantic），再实现具体功能；server/client 必须复用同一份模型，禁止两边各自手写 `dict` shape
- **SDK/示例强类型（Typed-by-Default）**：对外输入/输出/事件必须有明确的 typed model；禁止"直接拼 `dict`/随手 json.loads 后到处传"
- 不要凭记忆"编协议/编 SDK 字段"：以 `requirements.md`、官方 SDK/类型定义、以及仓库内 `anyagent.protocol.*` 为准
- **外部接口策略（OpenAI First + 资源型命名空间 SDK）**：
  - 对外 API 的主契约以 OpenAI Responses API + OpenAI 官方 SDK 兼容为第一优先级
  - `packages/anyagent` 的 Client SDK 以 `AnyAgent` 入口类 + 资源型命名空间模式（`client.responses.*` / `client.events.*` / `client.skills.*`）承载超集能力
  - 设计决策：`docs/architecture/decisions/openai-first-api-surface.md`

### 4.2 代码组织

- **层级化组织（禁止平铺）**：代码与文档新增内容必须按"功能/模块/领域"分层落目录；新增子目录后必须补该目录 `README.md`
- 避免重复实现与旁路：同一规则/策略/枚举必须保持单一真源
- **允许破坏性调整**：默认不做兼容层/兼容 shim，只保留"唯一、当前、最自然"的实现；允许删除/移动旧路径以维持 SSOT
- 错误处理要显式且可机读：避免吞异常或返回不可解析的字符串错误
- 结构化数据优先用 `pydantic` 模型/Typed 结构表达
- **Docstring 约束**：新增/修改 public module/class/function/method 必须写 docstring，第一行必须是单句摘要

### 4.3 安全默认

- 任何外部输入都要校验；任何可能含敏感信息的输出都要脱敏与限长
- 不泄露 secrets：不要把 `.env`、token、私钥、cookie、平台回调 payload 原文贴进对话/日志
- **CI 质量门**：变更应至少通过"文档护栏 + 离线 smoke"两层 gate；在线验收（依赖外部密钥）可作为可选 gate

---

## 5) 标准工作流（从想法到交付）

### 5.1 快速定位（推荐第一步）

```bash
python3 scripts/anyagent_progress.py --root .
```

- 展示每个模块 TODO 的"连续完成数"和"下一条 TODO（第几条 + file:line）"
- 若提示 `done_missing_evidence`，必须先补齐 `Impl/Module` 再继续推进

### 5.2 需求与任务对齐（必须）

- 在 `requirements.md` 找到对应章节（用 `req-*` 锚点引用）
- 在 `todo/` 选择正确模块文件新增/更新任务（不确定先放 `todo/backlog.md`）
- 任务行建议格式：`- [ ] P0/P1/P2 <任务>（Req: requirements.md#req-*）`

### 5.3 实现（Code as SSOT）

- 先改代码，再让文档与 TODO 引用代码事实（避免"文档先行、实现漂移"）
- 对外兼容面（Responses / Tool Runtime）：以协议模型与可观测字段为中心组织实现

### 5.4 实现后同步 TODO（必须）

完成某条任务后，立刻在对应 `todo/<module>.md`：

- 勾选为完成：`- [x] ...`
- 同一行补齐证据字段：`Impl: <path:line>；Module: <module>`
- 若涉及多文件：TODO 行只写**主入口**的 `Impl:`，其余放到下一行 `- refs:` 小列表

### 5.5 验证（必须）

见第 2 节。改了就要验，验了才算完。

---

## 6) 复合式工程（Compound Engineering）

每次改动都应产生复利。知识、工具、工作流都应沉淀为可复用的能力。

### 6.1 沉淀规则

- **工具沉淀**：重复执行 3 次以上的操作应脚本化，放入 `scripts/`
- **模式沉淀**：跨模块验证有效的设计模式应提炼到 `docs/architecture/`
- **约束沉淀**：多次改动中暴露的规则应回写到 `requirements.md` 或本文件

### 6.2 自迭代（Agent 改进 Agent 的工作环境）

Agent 在工作过程中应主动识别改进机会并提议：

- 发现 SSOT 漂移（文档与代码不一致）→ 修复并加固检查脚本
- 发现验证盲区（某类改动没有对应 smoke）→ 提议补充验收脚本
- 发现重复劳动（每次都要手动做某个步骤）→ 提议工具化
- 发现上下文噪音（不相关信息干扰定位）→ 优化文档结构或 pack tags

提议方式：在 `todo/backlog.md` 新增条目（标注 `[agent-suggested]`），由用户决定是否采纳。

### 6.3 渐进式探索

对于不确定的方向（新技术、新架构、新工具）：

1. **探索**：在 `docs/_dev/` 写下假设与调研笔记（标注"毕业条件"）
2. **试验**：用最小改动验证假设（允许在独立分支或 `.runs/` 中做实验）
3. **验证**：跑通验收闭环，确认假设成立
4. **沉淀**：将验证通过的结论迁移到长期维护文档，更新 SSOT
5. **复用**：提炼为可复用的工具/脚本/模式，让下一次探索更快

---

## 7) Git 与依赖纪律

### Git 安全规则

- 不要重写历史，不要做不可恢复的工作区清理
- 禁止破坏性命令：`git reset --hard`、`git checkout .`、`git clean -fd`、`git stash`
- staged 变更必须可控：不要用 `git add -A` / `git add .`；只 `git add <你本次改动的文件>`
- 任何需要 `git push` 的动作：必须先征求用户同意

### 依赖与供应链

- Python 依赖统一用 `uv` + `pyproject.toml` 管理；不要"临时 pip 安装"污染环境
- 没有充分理由不要新增依赖；若必须新增，先说明动机与风险
- 允许用 `uv run --with openai` 临时安装 OpenAI SDK 做验收（不修改 lock）

---

## 8) 一等公民概念（First-Class Concepts）

这些概念用于 **链路可观测性** 与 **可重放（replay）**，也是实现/排障/验收时必须对齐的术语。

### 标识与关联键

| 键 | 用途 |
|---|---|
| `agent_id` | 同一套服务内不同 agent 的稳定标识 |
| `session_key` | 外部平台线程/会话键（跨请求稳定） |
| `session_partition_key` | 并发分片键，固定为 `"{agent_id}::{session_key}"` |
| `response_id` / `run_id` | 一次 `POST /v1/responses` 的执行实例标识 |
| `idempotency_key` | 幂等去重键（请求级或 tool-call 级） |
| `tool_call_id` | 单次工具调用的稳定标识 |
| `tool_name` | 工具全名（如 `core.web_search`） |
| `trace_id` / `span_id` | 跨服务链路追踪字段 |
| `audit_ref` | 一次 tool 调用的稳定审计引用 |
| `seq` | run 内事件序号（单调递增） |

参考：`requirements.md#req-5-9`、`docs/security/audit-logging.md`、`docs/architecture/stateless-agent-service-architecture.md`、`docs/architecture/storage-minimal-design.md`。

### 产物与引用

任何"可复盘"的东西都应当能被引用到：

- **代码证据**：`path:line`（用于 TODO 的 `Impl:` 字段）
- **可复现命令**：一条或多条可直接执行的命令（带必要 env）
- **输入快照**：触发问题/需求的最小请求体（脱敏后）
- **输出/事件**：关键事件类型 + `response_id/run_id` + `last_seq`

本地临时产物默认放在 gitignore 的目录中：

- `.runs/`：本地 run/replay 相关临时文件
- `.cloud/`：第二大脑（不适合提交到仓库但又希望被 agent 复用的领域知识）

---

## 9) Definition of Done（完成标准）

- `todo/` 中对应任务已勾选，并保留 `Req: requirements.md#req-*`
- TODO 行包含 `Impl: path:line；Module: ...` 证据字段
- 有最小验证闭环（命令/验收文档/接口调用三选一，优先可自动化）
- 若涉及可观测性/重放相关变更：明确说明影响到哪些关联键与兼容性边界
- **复利检查**：这次改动是否有可沉淀的工具/模式/约束？如有，是否已落地？
