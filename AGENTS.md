# anyagent：AI Agent 自动化研发行为规范

本文件 `AGENTS.md` 的定位：**指导 AI Agent 在本仓库进行自动化研发的行为规范**。

核心目标：**构建配置化、无服务化的 Agent Server 内核 + SDK，一切研发流程可自动化、可自迭代、渐进式探索**。

本仓库按 **Agentic Engineering** 方式组织，围绕五个支柱：上下文工程、验证闭环、工具化、Agentic 代码库、复合式工程。

本文件是 agent harness，不是项目百科。它约束 agent 如何阅读上下文、判断边界、修改代码、同步文档和完成验证；具体接口字段、运行手册、架构决策、验收矩阵和迁移记录应保留在 `requirements.md`、`todo/*.md`、`docs/`、README 或代码真源中。

---

## 0) 项目定位

anyagent = **配置即服务的 Agent Server 内核 + SDK**：

- **Server Core**：内置 Agent API + Tool Runtime，`anyagent serve` 一条命令从 `.anyagent/` 配置启动 OpenAI Responses API 兼容服务
- **SDK**：`AnyAgent` Client SDK 提供 OpenAI 兼容层 + anyagent 精细层（tool/command 级 Stage Events）
- **Protocol SSOT**：`anyagent.protocol.*` 是所有 wire-level 协议的单一真源
- **安全边界**：Agent 可见资源但不可直接操作——密钥、凭证、tool policy 由 server 代理管理

本仓库是 protocol、server、SDK、runtime primitives、Tool Runtime、credential/connector contract 与文档的真源。消费侧仓库如何使用 anyagent 由各仓库自行维护，不在本仓 AGENTS.md 约束范围内。

---

## 1) 上下文工程（Context Engineering）

### 1.1 Agent-Naive Quickstart（首条消息 / 任务不明确时）

1. 阅读 `README.md` 与 `docs/architecture/overview/roadmap.md` 了解项目定位与当前阶段
2. 运行 `python3 scripts/anyagent_progress.py --root .` 定位下一条 TODO
3. 从 `todo/*.md` 定位任务条目，回溯到 `requirements.md#req-*`
4. 不清晰时：向用户追问要改哪个模块

### 1.2 SSOT 地图与引用约定

#### 文档真源表

| 层级 | 真源 | 职责 | 引用格式 |
|---|---|---|---|
| 行为规范 | `AGENTS.md` | agent 协作纪律、上下文读取、文档 stewardship | 本文件内 `§N` 章节号 |
| 需求 | `requirements.md` | What/Why,稳定锚点 | `requirements.md#req-*` |
| 任务 | `todo/*.md` | When/Progress,每条任务挂 `Req:` 锚点 | `todo/<module>.md` |
| 架构/契约 | `docs/architecture/`、`docs/security/`、`docs/acceptance/`、`docs/performance/` | How/Contract,长期维护 | 完整相对路径 `docs/architecture/overview/roadmap.md` |
| 代码 | `packages/anyagent/src/anyagent/` | 行为真源(How/Truth) | Python 模块路径 `anyagent.protocol.*` 或文件路径 `path:line` |
| 研发草案 | `docs/_dev/`、`docs/_notes/` | 非稳定,不作为引用目标 | — |
| Repo 内置技能 | `.agents/skills/` | 指导基于 anyagent 开发、调试和配置业务仓库的 agent 可复用能力 | `.agents/skills/<skill>/SKILL.md` |
| 人类入口 | `README.md` | 业务使用者主入口 | — |

#### 引用约定

引用其他文档或代码时,遵循以下规则:

1. **路径引用**:使用仓库根相对路径,带文件后缀。例:`docs/architecture/overview/roadmap.md`、`todo/sdk.md`。
2. **模块引用**:引用 Python 模块时用点分路径。例:`anyagent.protocol.events`、`anyagent.storage`。
3. **代码定位**:需要精确到行时用 `path:line` 格式。例:`packages/anyagent/src/anyagent/server/app.py:42`。
4. **需求锚点**:统一用 `requirements.md#req-*` 格式,反引号包裹完整锚点。
5. **不跨仓引用**:本仓文档不使用 `../` 引用其他仓库路径。消费侧仓库的行为由各仓库自行约束。
6. **双向 cite 最低要求**:
   - `todo/*.md` 每条任务必须 cite `requirements.md#req-*`
   - `docs/architecture/overview/roadmap.md` 每个 Phase 必须 cite 对应 `todo/<module>.md`
   - `docs/architecture/decisions/*.md` 必须被至少一个 `todo/*.md` 或 `roadmap.md` cite

当代码变更影响公开 API、wire contract、SDK 类型、配置、运行方式、用户可见行为或模块归属时，同轮更新最贴近的真源文档。不要把同一条规则复制到多个地方；必要时用链接指向真源。

当框架迭代影响业务仓库如何基于 anyagent 开发 Agent Server、初始化 `.anyagent/`、配置 agent/tool/skill/MCP/sandbox/credential/storage、调试运行时或部署各模块时，同轮检查并必要时更新 `.agents/skills/anyagent-dev/`。该 skill 是面向消费侧仓库的 repo-level 开发助手，不替代 `README.md`、`requirements.md` 或 `docs/architecture/` 真源；只沉淀 agent 执行业务仓库开发所需的最小工作流与索引。

### 1.3 核心目录结构

```text
packages/anyagent/src/anyagent/
  protocol/          # 协议 SSOT
    sandbox.py       # Sandbox 策略模型（SandboxPolicy/NetworkSandboxPolicy/ResourceLimits）
  agent_runtime/     # Agent loop 运行时
    loop/            # pydantic-ai 适配（模型映射、tool wrap、OTLP、hooks）
    tool_execution.py # Tool Runtime execute / manifest
    tool_loop.py     # run_tool_loop_* 对外合同
    model_providers/ # ModelProvider 协议、OpenAI 默认工厂、kind 目录
  skills/            # Skills 系统
  mcp/               # MCP server 管理
  gateway/           # 会话/路由
  tool_runtime/      # 工具注册、Tool Runtime contract/client/server 形态
  storage/           # 共享存储模型/契约/replay/runtime、reference external adapters 与运维语义
  plugins/           # Core 侧插件 API/loader/model
  server/            # 内置 Agent Server + 共享服务层 + production runtime shell
    routes/          # APIRouter 路由（distributed/internal/optional responses 与内置 app 路由）
    handlers/        # 路由共享 helper（auth、HTTP errors、SSE、persistence、health 等）
    responses/       # Responses 执行/幂等/流式/会话持久化管线
    persistence/     # server 内部事件/run/session/telemetry store 与 manifest cache
    runtime/         # in-process/distributed runtime、session lock、workspace env
    config/          # server settings 与请求边界解析/校验
    db/              # built-in server storage migration CLI glue 与 Postgres schema helper
    plugins/         # server 侧插件 capability matrix
    sandbox/         # Sandbox 后端（SandboxManager + OpenSandbox/External/LocalUnsafe）
    security/        # Credential Vault / Tool Policy
  config/            # anyagent.yaml、Agent Pack、模型选择与配置合并
  agent_api_client.py # Client SDK
  cli.py             # CLI 入口
```

### 1.4 渐进式披露

- 用 `python3 scripts/docs/pack.py --tags <topic>` 筛出最小文档上下文
- 先搜后读：优先 `rg`/`git grep` 定位入口
- 避免上下文污染：用摘要 + `path:line` + 可复现命令替代大段内容

### 1.5 Agent Loop 与生态工具设计原则

以下原则适用于：

- `agent_runtime/` 中的 agent loop、tool loop、session runtime
- `tool_runtime/`、`skills/`、`mcp/`、`server/` 的对外可见能力面
- `AnyAgent` SDK、Stage Events、help/explain、docs/acceptance 与调试入口

#### Everything Reach-able

- 任何 agent 可见能力都必须能从入口追到事实来源：能力描述 -> tool manifest / protocol model / handler / docs / acceptance。
- 任何底层实体也必须可反查上层语义：raw tool、event type、tool_call、credential/policy、handler 不能脱离所属能力独立漂浮。
- 设计新抽象时，必须明确“如何发现、如何定位、如何验证、如何回放”。

#### Gradual Disclosure

- 默认先暴露最小可行动信息：能力分类、稳定名称、下一步入口。
- 参数 schema、内部扩展字段、调试细节、底层 raw tool 列表按需展开，不在主路径一次性全部暴露。
- SDK、docs、help、manifest 的主路径应保持低噪声，但必须提供继续深入的可达路径。

#### Cite Bidirectional Linking

- 高层抽象必须能 cite 到低层事实：能力名 -> tool 名、event.type、协议模型、实现路径、验收脚本。
- 低层实体必须能反向链接回高层语义：raw tool / event / handler -> 所属能力、帮助入口、使用场景、相关文档。
- 事件与调试输出优先保留稳定锚点：`agent_id`、`response_id`、`tool_call_id`、`trace_id`、`seq`、`credential_id`、`path:line`。

---

## 2) 验证闭环（Agentic Validation）

### 2.1 实现中的自验证

- **改了就要验**：每次代码改动后主动执行相关验证
- 优先选择最小且可复现的验证：
  - 本地启动验证：`anyagent serve`（使用本仓 `tests/fixtures/` 或 `docs/acceptance/` 中的 workspace）
  - 验收文档：`docs/acceptance/`
  - smoke 脚本：`tests/`

### 2.2 可观测闭环

- 每次工具执行可追踪（Stage Events）
- 事件可重放（`seq` 单调递增 + `last_seq` 补发）
- 幂等可解释
- 敏感信息不落盘

### 2.3 交付输出约定

- **结论一句话**
- **证据链**：`requirements.md#req-*` + `todo/<module>.md` + `Impl: path:line`
- **如何复现**：最小命令 + 必要 env
- **如何验证**：最小验收脚本

---

## 3) 工具化（Agentic Tooling）

### 3.1 已有工具

- `python3 scripts/anyagent_progress.py --root .` — 进度定位
- `python3 scripts/docs/check.py --root .` — 文档断链检查
- `python3 scripts/docs/pack.py --tags <topic>` — 渐进式上下文筛选
- `python3 scripts/docs/index.py --root .` — docs 派生索引查看（默认 stdout）

### 3.2 工具化意识

- 发现摩擦 → 提议工具化
- 能脚本跑的不手动跑
- 长时间任务用后台模式

---

## 4) Agentic 代码库

### 4.1 协议与类型系统

- **Protocol-First**：新增/修改协议必须先更新 `anyagent.protocol.*`
- **Boundary Data Parsing**：HTTP/CLI/SDK/存储/文件/第三方工具输出进入系统边界时要做一次校验和归一化，内部主路径尽量只传已知形状的数据。
- **SDK/示例强类型**：输入/输出/事件必须有 typed model；SDK 业务边界模型集中从 `anyagent.types` 导出，`anyagent.protocol.*` 仍是 wire-level SSOT。
- **外部接口策略**：OpenAI Responses API 兼容为第一优先级，`AnyAgent` SDK 承载超集能力

### 4.2 代码组织

- 层级化组织，禁止平铺
- 允许破坏性调整，不做兼容层
- `pydantic` 模型优先
- 严格维护模块边界和数据流向；新增 facade、adapter、store、runtime service 时，要能说明所属层、入口、下游 contract 和验证点。

### 4.3 Agent Loop / Tool Ecosystem 具体约束

- `agent loop` 的高层语义必须能落到可追踪事件与稳定标识，不做“看起来工作了但无法解释”的黑箱流程。
- tool manifest / skill registry / MCP discovery 的设计应优先表达能力边界与归属关系，而不是仅暴露原始实现细节。
- help / explain / docs / acceptance 输出要支持从“能力 -> 实现”与“实现 -> 能力”双向跳转。
- 新增生态工具或扩展字段时，优先考虑是否能被 SDK、文档、验收和调试链路稳定引用；不能引用的字段要谨慎暴露。

### 4.4 安全默认

- 外部输入校验；敏感输出脱敏限长
- 不泄露 secrets
- **沙箱内自由，沙箱外隔离**：Agent 通过 `exec` tool 在沙箱中执行命令、发起网络请求、读写文件——沙箱不挂载凭证，egress 策略阻止访问内部服务
- **策略-后端分离**（参考 Codex）：策略定义在 `anyagent.protocol.sandbox`，后端可插拔（OpenSandbox / External / LocalUnsafe）
- **会话隔离**：per-session sandbox，同 session 内命令共享文件系统（有状态工作流）
- **运行时无感**：agent loop 不感知沙箱后端，`exec` tool 的 handler 由 SandboxManager 自动路由
- Credential Vault 代理注入：Agent 只见 credential_id，server 负责 resolve 和注入

---

## 5) 标准工作流

### 5.1 快速定位

```bash
python3 scripts/anyagent_progress.py --root .
```

### 5.2 需求与任务对齐

- 在 `requirements.md` 找到对应章节
- 在 `todo/` 选择正确模块文件新增/更新任务

### 5.3 实现

- 先改代码，再让文档与 TODO 引用代码事实

### 5.4 实现后同步 TODO

- 勾选为完成 + 补齐 `Impl: path:line` + `Module:` 证据

### 5.5 验证

改了就要验，验了才算完。

---

## 6) 复合式工程

### 6.1 沉淀规则

- 重复 3 次以上 → 脚本化到 `scripts/`
- 对版本提升、文档检查、发布巡检、Yunxiao pipeline/packages 查询、协议导出/对比等重复性、持久性工作，Agent 应主动沉淀到仓库绑定的 TypeScript `anyagent-dev-cli`，而不是只在当前轮手动执行。
- 使用 `anyagent-dev-cli` 前，先运行 `scripts/anyagent-dev-cli doctor` 或已安装的 `anyagent-dev-cli doctor` 确认 CLI 可用；默认输出使用 Markdown，只有需要机器消费时才显式传 `--json`。
- `anyagent-dev-cli` 的源码放在 `tools/anyagent-dev-cli/`，通过 `scripts/anyagent-dev-cli` 提供本仓稳定入口；新增命令要保留清晰参数、默认 Markdown 输出、显式 `--json` 机器可读输出、可复现验证和低噪声输出，并登记到 `scripts/README.md`。
- 每次开发或修改 `anyagent-dev-cli` 后，必须运行 `npm --prefix tools/anyagent-dev-cli run install:local` 完成构建与本地安装，再从仓库外目录 smoke test，例如 `cd /tmp && anyagent-dev-cli doctor`。
- 当前版本提升案例应使用 `scripts/anyagent-dev-cli version bump <version> --dry-run` 校验，再去掉 `--dry-run` 写入；不要再新增分散的单用途版本脚本。
- 跨模块有效模式 → 提炼到 `docs/architecture/`
- 多次暴露的规则 → 回写到 `requirements.md` 或本文件

### 6.2 自迭代

Agent 应主动识别改进机会：SSOT 漂移 → 修复；验证盲区 → 补 smoke；重复劳动 → 工具化；工具稳定复用 → 收敛到 `anyagent-dev-cli`。

当任务出现以下信号时，Agent 应自动判断是否沉淀到 `anyagent-dev-cli`，无需等待用户再次提醒：

1. 同一流程需要跨多个文件、命令或外部系统重复执行。
2. 操作容易漏步骤、漏版本源、漏文档、漏验证或输出过长。
3. 结果需要给后续 agent 或 CI 复用。
4. 任务涉及发布、构建、Yunxiao pipeline/packages 查询、协议导出/对比、文档 guardrail、TODO 证据整理等长期维护面。

若判断应沉淀，默认工作流是：在 `tools/anyagent-dev-cli/src/` 新增/扩展命令 → 更新 `tools/anyagent-dev-cli/README.md` 与 `scripts/README.md` → 运行 `npm --prefix tools/anyagent-dev-cli run install:local` → 从仓库外目录 smoke test → 最终回复说明命令、验证和是否已安装。

---

## 7) Git 与依赖纪律

### Git 安全规则

- 不重写历史，不做不可恢复的清理
- 不用 `git add -A`，只 add 本次改动的文件
- `git push` 必须先征求用户同意

### 本地质量门

- 提交前必须过本地门禁，不要把 unit / pytest 失败留到 GitHub Actions 才发现。设计真源：`docs/architecture/engineering/ci-pipeline.md`。
- 若 `git config --get core.hooksPath` 不是 `.githooks`，先运行 `bash scripts/install-git-hooks.sh`。
- `git commit` 跑 docs guardrails + `tests/unit`；`git push` 跑 pytest regressions + offline smokes。
- 禁止 `git commit --no-verify` / `git push --no-verify`，除非用户明确要求跳过。
- 仅在用户明确要求时使用 `ANYAGENT_SKIP_GIT_HOOKS=1`。

### 发版与 CD

- 本项目代码有修改且需要发布新版本时，必须同步提升版本号；优先使用 `scripts/anyagent-dev-cli version bump <version> --dry-run` 校验，再去掉 `--dry-run` 写入。当前版本真源至少包含 `packages/anyagent/pyproject.toml`、`packages/anyagent/src/anyagent/__init__.py`、`packages/anyagent/src/anyagent/tool_runtime/__init__.py` 以及内置 FastAPI app 的 `version` 参数。
- 发布路径为：本地完成实现、TODO/文档同步、验证与版本提升后，经用户确认推送到 GitHub `main`（`https://github.com/Lyrik-AI/AnyAgent`，本仓 `origin`）。GitHub Actions 的 `publish-packages` job 只构建 Python SDK，并发布到 Yunxiao Packages PyPI。版本已存在时该 job 成功并跳过上传。步骤真源：`docs/release-checklist.md`。构建编排真源：`docs/architecture/engineering/ci-pipeline.md`。
- 发版后确认该 job 成功，并查询 Yunxiao Packages 中的对应版本；若无法访问 GitHub Actions 或 Yunxiao Packages，在最终回复中说明未完成的远端验证与需要复现的查询条件。

### 依赖与供应链

- Python 依赖统一用 `uv` + `pyproject.toml`
- 没有充分理由不新增依赖

---

## 8) 一等公民概念

### 标识与关联键


| 键                        | 用途                                  |
| ------------------------ | ----------------------------------- |
| `agent_id`               | 同一套服务内不同 agent 的稳定标识                |
| `session_key`            | 外部平台线程/会话键                          |
| `session_partition_key`  | 并发分片键 `"{agent_id}::{session_key}"` |
| `response_id` / `run_id` | 一次 `POST /v1/responses` 的执行实例       |
| `idempotency_key`        | 幂等去重键                               |
| `tool_call_id`           | 单次工具调用标识                            |
| `credential_id`          | 凭证引用标识（agent 不见原值）                  |
| `seq`                    | run 内事件序号（单调递增）                     |


---

## 9) Definition of Done

- `todo/` 中任务已勾选，包含 `Req:` + `Impl:` + `Module:` 证据
- 有最小验证闭环；本仓代码改动在 commit 前必须过本地 git hooks（`docs/architecture/engineering/ci-pipeline.md` Gate 0）
- 若涉及安全边界变更：明确说明影响
- 若本次交付需要发版：版本号已同步提升，用户已确认并完成推送到 GitHub `main`，且 GitHub Actions `publish-packages` 成功、Yunxiao Packages 上能看到对应版本
- 引用完整性：`python3 scripts/docs/check.py --root .` 无断链报错
- 双向 cite 检查：新增/修改的 todo、docs、ADR 满足 §1.2 引用约定中的双向 cite 最低要求
- 复利检查：是否有可沉淀的工具/模式/约束
