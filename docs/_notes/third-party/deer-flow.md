# DeerFlow 可参考设计模式

> ByteDance DeerFlow v2 — Deep Exploration and Efficient Research Flow
> 定位：重量级全栈 Super Agent 应用（LangGraph + Next.js）
> 与 anyagent 的关系：不同层级，但以下模式可借鉴

---

## 1. Middleware Chain 模式

**核心思路**：Agent 运行时通过有序 middleware 链组合能力，每个 middleware 提供 `before_model` / `after_model` / `wrap_tool_call` 三个钩子。

**组装方式**：
- 基础链 8 个（ThreadData → Uploads → Sandbox → DanglingToolCall → LLMErrorHandling → Guardrail → SandboxAudit → ToolErrorHandling）
- 业务链 10 个按条件动态追加（Summarization、Todo、Vision、DeferredTool、SubagentLimit、LoopDetection 等）
- 顺序即优先级，ClarificationMiddleware 必须最后（通过 `Command(goto=END)` 中断流程）

**值得借鉴**：
- `lazy_init=True` 延迟初始化，条件中间件根据运行时 config 动态决定是否加入
- 对 anyagent：可在 agent runtime loop 中引入轻量 middleware 接口，让 tool error handling、guardrail、loop detection 等能力可插拔

**关键文件**：
- `backend/packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py`
- `backend/packages/harness/deerflow/agents/lead_agent/agent.py`

---

## 2. Sandbox 隔离

**核心思路**：Provider 模式管理 sandbox 生命周期，Agent 只看到虚拟路径。

**接口设计**：
- `Sandbox` ABC：`execute_command`、`read_file`、`write_file`、`list_dir`、`glob`、`grep`
- `SandboxProvider` ABC：`acquire(thread_id)` → `get(sandbox_id)` → `release(sandbox_id)`
- 通过 config 中类路径 + `resolve_class()` 反射加载，全局单例缓存

**虚拟路径系统**：
- Agent 看到 `/mnt/user-data/{workspace,uploads,outputs}`
- 物理映射到 `users/{user_id}/threads/{thread_id}/user-data/...`
- Local 通过 `PathMapping` 翻译，Docker AIO 通过 volume mount

**两种实现**：
- `LocalSandboxProvider`：本地文件系统 + LRU 缓存 256 个 per-thread sandbox
- `AioSandboxProvider`：Docker 容器隔离

**值得借鉴**：
- Provider 抽象 + 反射加载的模式，anyagent 的 sandbox backend 可以直接复用这个思路
- 虚拟路径翻译层让 agent 代码与物理存储解耦
- `asyncio.to_thread` 包装同步 acquire 避免阻塞事件循环

**关键文件**：
- `backend/packages/harness/deerflow/sandbox/sandbox.py`
- `backend/packages/harness/deerflow/sandbox/sandbox_provider.py`

---

## 3. Memory 系统

**核心思路**：LLM 驱动的事实提取 + 文件存储 + per-user 隔离。

**提取流程**：
- `MemoryUpdater._do_update_memory_sync()` 用独立 LLM 调用分析对话
- 输出结构化 JSON：`user` / `history` / `newFacts` / `factsToRemove`
- 用正则从 LLM 响应中提取第一个合法 JSON（容忍 markdown fence 包裹）

**存储与隔离**：
- 路径：`{base_dir}/users/{user_id}/memory.json`
- 缓存 key：`(user_id, agent_name)` 元组
- `FileMemoryStorage` 用 `threading.Lock` 保护缓存读写

**去重与容量控制**：
- 新 fact 按 `content.strip().casefold()` 去重
- 超过 `max_facts` 时按 confidence 排序截断

**异步安全**：
- 用 `ThreadPoolExecutor(max_workers=4)` 执行 sync LLM 调用
- 避免与 lead agent 共享的 async httpx 连接池冲突

**值得借鉴**：
- LLM 提取 fact 的 prompt 模式可以直接复用
- per-user 文件隔离简单有效，适合 anyagent 的轻量定位
- debounced 后台更新避免每轮对话都触发 memory 写入

**关键文件**：
- `backend/packages/harness/deerflow/agents/memory/updater.py`
- `backend/packages/harness/deerflow/agents/memory/storage.py`

---

## 4. MCP 集成

**核心思路**：配置文件声明 MCP servers，持久会话池管理连接，mtime 驱动缓存失效。

**配置加载**：
- `extensions_config.json` 定义 MCP servers
- `get_mcp_tools()` 每次从磁盘读取最新配置（不走缓存），确保 Gateway API 修改立即生效

**会话池**：
- `MCPSessionPool` 按 `(server_name, thread_id)` 维护持久 `ClientSession`
- LRU 淘汰（256 上限）
- 仅 stdio 传输走池化，HTTP/SSE 不池化（避免 TaskGroup 跨任务清理错误）

**缓存失效**：
- `_is_cache_stale()` 比较 `extensions_config.json` 的 `os.path.getmtime()`
- mtime 变化则 `reset_mcp_tools_cache()` 并关闭所有持久会话

**值得借鉴**：
- 会话池按 `(server_name, thread_id)` 隔离，避免跨 session 串扰
- mtime 轮询简单可靠，适合 anyagent 的轻量定位（无需 inotify/fswatch）
- stdio vs HTTP/SSE 区分池化策略是实践经验

**关键文件**：
- `backend/packages/harness/deerflow/mcp/tools.py`
- `backend/packages/harness/deerflow/mcp/cache.py`
- `backend/packages/harness/deerflow/mcp/session_pool.py`

---

## 5. Subagent 委派

**核心思路**：Lead Agent 通过标准 tool_call 触发子任务，后台线程池执行，SSE 事件流反馈进度。

**委派接口**：
- `@tool("task")` 接收 `description`、`prompt`、`subagent_type`
- Lead Agent 通过普通 tool_call 触发，无需特殊协议
- `SubagentLimitMiddleware` 在 `after_model` 截断超额并发（默认 MAX=3）

**执行模型**：
- `SubagentExecutor.execute_async()` 提交到 `ThreadPoolExecutor`
- task_tool 内部 5s 轮询等待结果
- 通过 `get_stream_writer()` 发送 `task_started`/`task_running`/`task_completed` SSE 事件

**隔离与安全**：
- Subagent 继承父 sandbox/thread_data
- 禁用 `task` tool（防递归嵌套）
- 模型可继承父模型或独立配置
- Skills allowlist 取父子交集

**取消机制**：
- `asyncio.CancelledError` 时调用 `request_cancel_background_task()` 协作取消
- shield 等待终态后清理

**值得借鉴**：
- "tool_call 即委派"的设计极简优雅，anyagent 的 multi-agent spawn 可参考
- 并发限制通过 middleware 而非 executor 层实现，关注点分离更清晰
- 禁用递归嵌套是必要的安全边界

**关键文件**：
- `backend/packages/harness/deerflow/tools/builtins/task_tool.py`
- `backend/packages/harness/deerflow/subagents/executor.py`

---

## 6. Config 热重载

**核心思路**：每次请求时 stat 文件 mtime，变化则重新加载，无需文件监听。

**机制**：
```
get_app_config() 每次调用:
1. 解析 config 路径
2. os.path.stat().st_mtime
3. 比较 path/mtime 是否变化
4. 变化则 _load_and_cache_app_config() 重新解析 YAML
```

**生效范围**：
- 即时生效：model、memory、tools、subagents 等运行时字段
- 需重启：database、checkpointer、sandbox.use、channels（lifespan 中一次性初始化）

**值得借鉴**：
- 纯轮询 stat 简单可靠，每次请求多一次 syscall 但无额外依赖
- 对 anyagent：agent.yaml 变更检测可直接用此模式
- 明确区分"热重载字段"和"冷重启字段"是好的设计决策

**关键文件**：
- `backend/packages/harness/deerflow/config/app_config.py:360-389`

---

## 总结：anyagent 可落地的借鉴点

| 优先级 | 模式 | anyagent 落地建议 |
|--------|------|-------------------|
| 高 | MCP 会话池 + mtime 缓存失效 | mcp.json 变更检测，按 (server, session) 池化连接 |
| 高 | Config 热重载 | agent.yaml mtime 检测，zero-downtime 更新 agent 配置 |
| 中 | Middleware chain | agent runtime loop 引入轻量 middleware 接口 |
| 中 | Subagent 委派 | multi-agent spawn 参考 tool_call 触发 + 并发限制 |
| 低 | Sandbox Provider | 当前 anyagent 已有 sandbox backend 抽象，可参考虚拟路径层 |
| 低 | Memory 系统 | LLM fact 提取可作为可选 plugin，非核心路径 |
