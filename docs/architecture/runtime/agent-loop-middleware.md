<!--
---
doc_kind: architecture
status: stable
tags: ["middleware", "agent-loop", "context-compaction", "loop-detection", "runtime"]
summary: 定义 anyagent agent loop 的 4-hook middleware 接口、内置上下文压缩与循环检测 middleware,以及 plugin middleware 的装载顺序与配置口径。
req: ["requirements.md#req-5"]
---
-->

# Agent Loop Middleware 架构

本文定义 anyagent agent loop 的 **middleware 扩展机制**:一个让循环检测、上下文压缩、审计等横切能力可配置、可替换、可组合的统一接口,以及两个内置 middleware 的设计。

要解决的问题很具体:agent loop 是一个 `model → tool → model → …` 的迭代过程,很多横切需求(防止模型在同一工具上死循环、长对话超出 context window、审计每次模型请求)都需要在迭代的固定位置插入逻辑。把这些逻辑直接写进 loop 主体会让 `tool_loop.py` 越来越臃肿且不可替换。middleware 把这些插入点收敛成 4 个稳定 hook,内置能力与 plugin 能力走同一条装载链路。

对应需求:`requirements.md#req-5`

## 1. 4-hook 接口

接口定义在 `packages/anyagent/src/anyagent/agent_runtime/middleware.py:55`(`AgentMiddleware` Protocol),围绕 agent loop 的一次迭代提供 4 个回调:

| Hook | 触发时机 | 返回类型 | 可改变什么 |
| --- | --- | --- | --- |
| `before_model_call` | 组装好请求体、调用模型**前** | `BeforeModelResult`(`:33`) | 改写请求体 `body`;`stop=True` 提前终止 loop |
| `after_model_call` | 模型返回、解析出 tool_calls **后** | `AfterModelResult`(`:39`) | `suppress_calls=True` 抹掉本轮 tool_calls 强制文本输出;`stop=True` 终止 |
| `before_tool_execute` | 执行单个工具**前** | `BeforeToolResult`(`:45`) | `skip=True` 跳过该工具;`override_output` 直接给定输出不执行 |
| `after_tool_execute` | 单个工具执行**后** | `AfterToolResult`(`:51`) | `result` 改写工具输出 |

每个 hook 都接收 `MiddlewareContext`(`:20`):携带 `agent_id`、`session_key`、`iter_index`(当前迭代序号)、`response_id`、`stage_event_sink`(用于发射 Stage Events)、以及一个跨迭代、跨 hook 共享的可变 `state: dict`(循环检测的滑动窗口、压缩的上一轮摘要都存在这里)。

`BaseMiddleware`(`:79`)提供 4 个 hook 的空实现,自定义 middleware 继承它后只覆盖关心的 hook 即可。

## 2. MiddlewareChain 的执行语义

多个 middleware 通过 `MiddlewareChain`(`:111`)按顺序组合。链的执行方向是刻意设计的:

- **`before_*` 正序**(`:119`、`:147`):按配置顺序依次执行。`before_model_call` 把上一个 middleware 改写后的 `body` 传给下一个(管道式叠加);任一返回 `stop` 即中断后续。
- **`after_*` 逆序**(`:131`、`:158`,`reversed(self._middlewares)`):后注册的先看到结果。这与"洋葱模型"一致——`after_tool_execute` 让靠后的 middleware 先改写输出,再交给靠前的。

接入点在 `packages/anyagent/src/anyagent/agent_runtime/tool_loop.py`:loop 入口构造 `MiddlewareContext`(`tool_loop.py:634`),每轮模型调用前后分别走 `_middleware_before_model`(`:644`)/`_middleware_after_model`(`:673`),工具执行包在 `_execute_one_tool_with_middleware`(`:87`)里。chain 为空时零开销(`MiddlewareChain.empty`,`middleware.py:116`)。

## 3. 装载与配置

middleware chain 由 `_build_agent_middleware_chain`(`packages/anyagent/src/anyagent/server/app.py:148`)按 agent pack 构建。配置入口是 `agent.yaml` 的 `runtime.middlewares`(`RuntimeSpec.middlewares: list[str]`,`packages/anyagent/src/anyagent/agent_packs.py:110`):

- **显式顺序**:`runtime.middlewares` 列出的字符串按声明顺序装载。内置 middleware 用别名 `loop_detection` / `context_compaction`(别名表 `app.py:141`);其余字符串当作 **classpath**(如 `my_plugin.middleware:AuditMiddleware`)由 `load_middleware_from_classpath`(`middleware.py` 同模块)动态导入。装载名做归一化:取 classpath 末段、小写、`-`→`_`(`app.py:155`)。plugin middleware 加载失败只 warning 跳过,不影响该 agent 运行(`app.py:184`)。
- **默认开启**:当 `runtime.middlewares` **未显式配置**时,默认装载 `["loop_detection", "context_compaction"]`(`app.py:150`),且各自受其 `enabled` 开关控制(`app.py:189`、`:196`)。即"开箱即用就有循环检测与压缩",但一旦用户显式声明 middlewares,则完全以声明为准(不再隐式追加)。

内置 middleware 的参数来自 `RuntimeSpec` 的子配置(`agent_packs.py:106`):`runtime.loop_detection`(window_size / warn_threshold / hard_limit / enabled)与 `runtime.context_compaction`(enabled / max_context_tokens / trigger_ratio / keep_recent_tokens)。

## 4. 内置 middleware:上下文压缩

`ContextCompactionMiddleware`(`packages/anyagent/src/anyagent/agent_runtime/middlewares/context_compaction.py:12`)在 `before_model_call` 中工作,目标是让长对话不超出 context window。

- **触发**:估算当前请求体 token 用量,超过 `max_context_tokens * trigger_ratio`(默认 `128000 * 0.8`)时压缩;未触发则发 skipped 事件原样放行(`:73`)。
- **cut-point 选择**:`_find_split_index`(`:118`)从尾部累积 `keep_recent_tokens`(默认 20000)确定保留窗口的切点,然后 `_move_split_away_from_tool_pair`(`:130`)把切点从 `tool_call → tool_result` 中间移开——**绝不在工具调用与其结果之间切断**,否则模型会看到"有结果没调用"的残缺历史。
- **迭代式摘要**:被切掉的旧历史交给模型生成 handoff 摘要(prompt 模板见 `:161`,保留 progress / decisions / next steps);已有摘要时,新摘要作为对旧摘要的 **UPDATE** 生成,而非每次从零重写。模型不可用时回退到本地结构化摘要 `_build_local_summary`(`:182`)。
- **事件**:压缩完成发射 `AnyAgentContextCompactedEvent`(`packages/anyagent/src/anyagent/protocol/stage_events.py:358`,字段含 tokens_before/after、messages_removed、summary_preview、strategy),SDK 消费方可感知压缩发生。

## 5. 内置 middleware:循环检测

`LoopDetectionMiddleware`(`packages/anyagent/src/anyagent/agent_runtime/middlewares/loop_detection.py:16`)默认开启,在 `after_model_call` 中检测模型是否在重复调用同一工具。

- **签名 + 滑动窗口**:对每个 tool_call 计算稳定签名 `tool_call_signature`(`:101`,name + 关键参数),压入 `MiddlewareContext.state` 里的 `deque(maxlen=window_size)`(默认 20,`:44`),统计窗口内同签名出现次数。
- **双阈值**:重复次数达 `warn_threshold`(默认 3)注入警告并发 `AnyAgentLoopWarningEvent`(`stage_events.py:371`);达 `hard_limit`(默认 5)返回 `suppress_calls=True` 抹掉 tool_calls、强制模型转文本输出,并发 `AnyAgentLoopTerminatedEvent`(`:380`)。`hard_limit` 被钳制为不小于 `warn_threshold`(`:20`)。

签名的"稳定"是关键:不同工具用不同的 salient 字段策略(如读文件按行号 bucket、写文件按全量参数 hash),避免把"读同一文件不同区段"误判为循环,也避免参数微小扰动绕过检测。

## 6. plugin middleware

plugin 通过 manifest 的 `middlewares` 字段声明 middleware classpath(见 [../integrations/platform-connectors.md](../integrations/platform-connectors.md)),框架按 `agent.yaml` 的 `runtime.middlewares` 顺序加载。这让第三方扩展能力(审计、限流、自定义改写)与内置能力共享同一条 chain,无需改动 loop 主体。plugin middleware 的能力维度记录在 `PluginCapabilityMatrix`(`packages/anyagent/src/anyagent/protocol/plugin_capabilities.py`)。

## 关联实现

- 接口与链:`packages/anyagent/src/anyagent/agent_runtime/middleware.py`
- 接入点:`packages/anyagent/src/anyagent/agent_runtime/tool_loop.py:87`、`:634`、`:644`、`:673`
- 装载与配置:`packages/anyagent/src/anyagent/server/app.py:148`、`packages/anyagent/src/anyagent/agent_packs.py:106`
- 内置压缩:`packages/anyagent/src/anyagent/agent_runtime/middlewares/context_compaction.py`
- 内置循环检测:`packages/anyagent/src/anyagent/agent_runtime/middlewares/loop_detection.py`
- Stage Events:`packages/anyagent/src/anyagent/protocol/stage_events.py:358`(compacted)、`:371`(loop warning)、`:380`(loop terminated)

## 参考

- [agent-packs-and-runtime-config.md](agent-packs-and-runtime-config.md):`agent.yaml` / `RuntimeSpec` 配置全貌
- [agent-server-runtime-entities.md](agent-server-runtime-entities.md):运行时实体分层与 agent loop 位置
- [../api/agent-api-client-stage-events.md](../api/agent-api-client-stage-events.md):Stage Events 在 SDK 侧的消费
- [multi-agent/multi-agent-collaboration.md](../multi-agent/multi-agent-collaboration.md):Sub-Agent 与循环检测的协作(循环检测作为 sub-agent 安全网)
