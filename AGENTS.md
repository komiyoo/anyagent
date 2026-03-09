# anyagent：AI Agent 自动化研发行为规范

本文件 `AGENTS.md` 的定位：**指导 AI Agent 在本仓库进行自动化研发的行为规范**。

核心目标：**构建配置化、无服务化的 Agent Server 内核 + SDK，一切研发流程可自动化、可自迭代、渐进式探索**。

本仓库按 **Agentic Engineering** 方式组织，围绕五个支柱：上下文工程、验证闭环、工具化、Agentic 代码库、复合式工程。

---

## 0) 项目定位

anyagent = **配置即服务的 Agent Server 内核 + SDK**：

- **Server Core**：内置 Agent API + Tool Runtime，`anyagent serve` 一条命令从 `.agents/` 配置启动 OpenAI Responses API 兼容服务
- **SDK**：`AnyAgent` Client SDK 提供 OpenAI 兼容层 + anyagent 精细层（tool/command 级 Stage Events）
- **Protocol SSOT**：`anyagent.protocol.*` 是所有 wire-level 协议的单一真源
- **安全边界**：Agent 可见资源但不可直接操作——密钥、凭证、tool policy 由 server 代理管理

同级项目 `../anyagent-apps` 消费本仓库，扩展为生产级分布式部署（PG/Redis 持久化、独立 Tool Runtime、平台 Connector）。

---

## 1) 上下文工程（Context Engineering）

### 1.1 Agent-Naive Quickstart（首条消息 / 任务不明确时）

1. 阅读 `README.md` 与 `docs/architecture/roadmap.md` 了解项目定位与当前阶段
2. 运行 `python3 scripts/anyagent_progress.py --root .` 定位下一条 TODO
3. 从 `todo/*.md` 定位任务条目，回溯到 `requirements.md#req-*`
4. 不清晰时：向用户追问要改哪个模块

### 1.2 SSOT 地图

- **需求真源（What/Why）**：`requirements.md`（锚点 `requirements.md#req-*`）
- **任务真源（When/Who/Progress）**：`todo/*.md`
- **行为真源（How/Truth）**：仓库代码以 `packages/anyagent/` 为主
- **长期维护文档（How/Contract）**：`docs/architecture|security|acceptance|performance/`
- **研发草案（非稳定）**：`docs/_dev/`、`docs/_notes/`

### 1.3 核心目录结构

```text
packages/anyagent/src/anyagent/
  protocol/          # 协议 SSOT
    sandbox.py       # Sandbox 策略模型（SandboxPolicy/NetworkSandboxPolicy/ResourceLimits）
  agent_runtime/     # Agent loop 运行时
  skills/            # Skills 系统
  mcp/               # MCP server 管理
  gateway/           # 会话/路由
  tool_runtime/      # 工具注册
  server/            # 内置 Agent Server (Phase 1 新增)
    sandbox/         # Sandbox 后端（SandboxManager + OpenSandbox/External/LocalUnsafe）
    security/        # Credential Vault / Tool Policy
  agent_packs.py     # Agent Packs 配置加载
  agent_api_client.py # Client SDK
  cli.py             # CLI 入口
```

### 1.4 渐进式披露

- 用 `python3 scripts/docs/pack.py --tags <topic>` 筛出最小文档上下文
- 先搜后读：优先 `rg`/`git grep` 定位入口
- 避免上下文污染：用摘要 + `path:line` + 可复现命令替代大段内容

---

## 2) 验证闭环（Agentic Validation）

### 2.1 实现中的自验证

- **改了就要验**：每次代码改动后主动执行相关验证
- 优先选择最小且可复现的验证：
  - 本地启动验证：`anyagent serve --workspace ../anyagent-apps/examples/demo-workspace`
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
- `python3 scripts/docs/index.py` — docs manifest 生成

### 3.2 工具化意识

- 发现摩擦 → 提议工具化
- 能脚本跑的不手动跑
- 长时间任务用后台模式

---

## 4) Agentic 代码库

### 4.1 协议与类型系统

- **Protocol-First**：新增/修改协议必须先更新 `anyagent.protocol.*`
- **SDK/示例强类型**：输入/输出/事件必须有 typed model
- **外部接口策略**：OpenAI Responses API 兼容为第一优先级，`AnyAgent` SDK 承载超集能力

### 4.2 代码组织

- 层级化组织，禁止平铺
- 允许破坏性调整，不做兼容层
- `pydantic` 模型优先

### 4.3 安全默认

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
- 跨模块有效模式 → 提炼到 `docs/architecture/`
- 多次暴露的规则 → 回写到 `requirements.md` 或本文件

### 6.2 自迭代

Agent 应主动识别改进机会：SSOT 漂移 → 修复；验证盲区 → 补 smoke；重复劳动 → 工具化。

---

## 7) Git 与依赖纪律

### Git 安全规则

- 不重写历史，不做不可恢复的清理
- 不用 `git add -A`，只 add 本次改动的文件
- `git push` 必须先征求用户同意

### 依赖与供应链

- Python 依赖统一用 `uv` + `pyproject.toml`
- 没有充分理由不新增依赖

---

## 8) 一等公民概念

### 标识与关联键

| 键 | 用途 |
|---|---|
| `agent_id` | 同一套服务内不同 agent 的稳定标识 |
| `session_key` | 外部平台线程/会话键 |
| `session_partition_key` | 并发分片键 `"{agent_id}::{session_key}"` |
| `response_id` / `run_id` | 一次 `POST /v1/responses` 的执行实例 |
| `idempotency_key` | 幂等去重键 |
| `tool_call_id` | 单次工具调用标识 |
| `credential_id` | 凭证引用标识（agent 不见原值） |
| `seq` | run 内事件序号（单调递增） |

---

## 9) Definition of Done

- `todo/` 中任务已勾选，包含 `Req:` + `Impl:` + `Module:` 证据
- 有最小验证闭环
- 若涉及安全边界变更：明确说明影响
- 复利检查：是否有可沉淀的工具/模式/约束
