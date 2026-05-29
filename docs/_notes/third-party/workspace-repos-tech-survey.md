# 工作区仓库技术方案调研报告

> 调研日期：2026-05-29
> 调研范围：anyagnet-workspace 下 codex、deer-flow、pi-mono、openclaw、HiClaw、NextChat
> 目的：评估各仓库技术方案对 anyagent 的借鉴价值，指导 Phase 1.8 及后续规划

---

## 1. 调研结论

anyagent 应从工作区仓库中吸纳以下技术方案，按三个维度（Runtime、框架、SDK）分层落地：

| 维度 | 核心借鉴 | 来源 |
|------|---------|------|
| **Runtime** | 循环检测算法、上下文压缩 prompt + cut-point、Sub-Agent 深度/并发限制 | DeerFlow + Codex + Pi-mono |
| **框架** | 4-hook Middleware 接口、Plugin Manifest v1（含 middlewares 字段）、Config 热重载 | DeerFlow + Pi-mono + OpenClaw |
| **SDK** | Sub-Agent/Compaction/LoopDetection Stage Events、conformance fixtures 覆盖 | Codex + DeerFlow |

---

## 2. 各仓库定位与可借鉴模式

### 2.1 Codex（Rust）— 终端编程 Agent

**可借鉴**：
- 上下文压缩 prompt（`templates/compact/prompt.md`）：10 行 handoff summary 模板
- Remote compaction v2：调用 `/responses/compact` API 的服务端压缩路径
- Multi-Agent v2：mailbox 通信、fork mode（FullHistory / LastNTurns）、depth limit
- Batch spawn（spawn_agents_on_csv）：FuturesUnordered 并发，默认 16 最大 64
- AGENTS.md 层级遍历：从 cwd 到 project root 逐层收集

### 2.2 DeerFlow（Python/LangGraph）— Super Agent 应用

**可借鉴**：
- LoopDetectionMiddleware：hash + 滑动窗口(20) + 双阈值(warn 3 / hard 5) + stable_tool_key
- SummarizationMiddleware：token 阈值触发 + 保留近 N 条 + LLM 摘要 + skill rescue
- SubagentExecutor：`task()` tool 模式 + scheduler 线程池 + 并发限制(3) + 超时(15min)
- Config 热重载：mtime 轮询，区分热/冷字段
- MCP 会话池：按 (server_name, thread_id) 池化，LRU 256，stdio/HTTP 区分策略
- Memory 系统：LLM fact 提取 + 置信度 + 去重 + per-user 文件隔离

### 2.3 Pi-mono（TypeScript）— 可扩展终端 Agent 框架

**可借鉴**：
- Compaction cut-point 算法：从末尾向前累积 token → 找有效切割边界（不在 tool chain 中间切）
- Split-turn 处理：切割点落在 turn 中间时单独生成 turn prefix summary
- 迭代式摘要更新：新摘要作为 UPDATE 生成，保留累积上下文
- Extension API：registerTool + registerCommand + 10+ lifecycle events
- Session tree：append-only JSONL + branch navigation + branch summary

### 2.4 OpenClaw（TypeScript）— Claude Code 开源变体

**可借鉴**：
- Context Engine slot：pluggable interface（bootstrap → maintain → assemble → compact）
- 30+ Hook 体系：before_tool_call / after_tool_call / before_compaction / after_compaction 等
- Tool Availability Expression：组合条件树控制工具可见性
- Runtime quarantine：非默认 engine 失败时自动隔离回退

### 2.5 HiClaw（Go + K8s）— 多 Agent 编排平台

**可借鉴**：
- DAG 任务执行：dependsOn 声明依赖，系统追踪 ready_nodes
- Seed-only 配置模式：controller 只首次写入，之后 agent 拥有文件所有权
- Channel Policy：细粒度消息过滤，控制 agent 间通信权限
- Backend 抽象（Docker vs K8s）：同一 controller 适配不同部署形态

---

## 3. 框架扩展模型建议

### 3.1 4-hook Middleware 接口

```python
class AgentMiddleware(Protocol):
    async def before_model_call(self, *, messages, tools, context) -> BeforeModelResult
    async def after_model_call(self, *, response, context) -> AfterModelResult
    async def before_tool_execute(self, *, tool_name, arguments, context) -> BeforeToolResult
    async def after_tool_execute(self, *, tool_name, result, context) -> AfterToolResult
```

覆盖场景：上下文压缩、循环检测、审批流、审计、记忆注入、工具过滤、错误归一化。

### 3.2 agent.yaml 配置面

```yaml
runtime:
  middlewares:
    - loop_detection
    - context_compaction
    - "plugins.my_audit:AuditMiddleware"
  compaction:
    strategy: summarize
    trigger_threshold: 0.8
    keep_recent_tokens: 20000
  loop_detection:
    warn_threshold: 3
    hard_limit: 5
    window_size: 20
  subagent:
    max_concurrent: 3
    max_depth: 3
    run_timeout_seconds: 900
```

### 3.3 Plugin Manifest v1

```yaml
name: my-plugin
tools: [...]
skills: [...]
mcp_servers: [...]
middlewares:
  - "my_plugin.middleware:AuditMiddleware"
hooks:
  on_agent_start: "my_plugin:on_start"
  on_agent_end: "my_plugin:on_end"
```

---

## 4. SDK 消费面设计

Phase 1.8 新增 Stage Event types：
- `subagent.spawned` / `subagent.progress` / `subagent.completed`
- `context.compacted`（tokens_before, tokens_after, summary_preview）
- `agent.loop_warning` / `agent.loop_terminated`

SDK namespace 扩展：
- `client.events.stream_typed(response_id, include_subagent_events=True)`
- conformance fixtures 覆盖新 event types

---

## 5. 参考文件索引

| 仓库 | 关键文件 |
|------|---------|
| Codex | `codex-rs/core/templates/compact/prompt.md`, `src/compact.rs`, `src/tools/handlers/agent_jobs.rs` |
| DeerFlow | `agents/middlewares/loop_detection_middleware.py`, `agents/middlewares/summarization_middleware.py`, `subagents/executor.py` |
| Pi-mono | `packages/agent/src/harness/compaction/compaction.ts`, `packages/coding-agent/src/core/extensions/types.ts` |
| OpenClaw | `src/context-engine/types.ts`, `src/plugins/hook-types.ts`, `src/tools/planner.ts` |
| HiClaw | `hiclaw-controller/internal/service/deployer.go`, `manager/agent/skills/task-coordination/SKILL.md` |
