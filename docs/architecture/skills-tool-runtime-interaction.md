# Skills ↔ Tool Runtime 交互关系（manifest/execute 合约）

对应需求：`requirements.md#req-12-8`

本文件的目标是把 **Skills 动态披露** 与 **Tool Runtime** 的交互关系固化为一份“可复盘、可校验”的合约说明，避免在后续演进中出现字段含义漂移或多套实现。

## 1. 角色分工（Who owns what）

- Skill（`SKILL.md` + `agents/openai.yaml`）决定：
  - 注入到模型的指令（prompt injection）
  - 依赖哪些工具（dependencies.tools → `requested_tool_names`）
  -（可选）扩展 Tool Context / policy（权限上限仍由服务端约束）
- Agent API（`POST /v1/responses`）负责：
  - 解析 agent_id/session_key
  - 选择技能（AgentSpec defaults + metadata.skills + `$skill` mention）
  - 构建本次 run 的 `PromptEnvelope`（稳定前缀 + 结构化 contextual fragments）
  - 汇总工具可见性请求集合 `requested_tool_names`
  - 调用 Tool Runtime `manifest` 获取最终的 `tools[]` 并注入上游请求
  - 在工具调用 loop 中调用 Tool Runtime `execute`
- Tool Runtime 负责：
  - 根据 `requested_tool_names` + policy/context 过滤可见工具（manifest）
  - 执行工具（execute）
  - 重新校验策略（不信任上游输入）

## 2. 端到端数据流（What happens in one run）

以 Agent API 的 `POST /v1/responses` 为例（stream 与非 stream 两条路径共用同一套 manifest/execute 逻辑）：

0) PromptEnvelope 组装
   - Agent API 在真正调用上游模型前，先组装统一的 `PromptEnvelope`
   - `PromptEnvelope` / `PromptContextAudit` / session snapshot prompt context 的类型真源位于 `anyagent.protocol.prompt_context` 与 `anyagent.protocol.session_snapshot`
   - 稳定层至少包括：
     - `AGENTS.md` 结构化片段
     - 已选 skills 的结构化片段
     - 稳定 `prompt_cache_key`
   - contextual 层至少可包括：`<environment_context>` 等运行时上下文片段
   - 高波动层（当前 user 输入、tool output、resume 恢复内容）不进入稳定前缀

1) Skills 选择
   - `selected_skills` 由 Skills 子系统按优先级决定（详见 `requirements.md#req-12-6-1`）
   - `enabled_skills` 目前用于传给 Tool Runtime 作为“将来扩展字段”（Tool Runtime v0 manifest 当前不消费该字段）

2) 计算 `requested_tool_names`（三源并集，去重保持稳定顺序）
   - AgentSpec: `pack.spec.tools.requested_tool_names`
   - Skills: `requested_tool_names_for_skills(selected_skills)`（来自 skill 的 `agents/openai.yaml` → `dependencies.tools[]`）
   - External request: 从 caller 提供的 `tools[]` 中抽取 function.name

3) 生成 Tool Context（server-generated）
   - 忽略 caller 提供的 `metadata.context.policy`（安全：上游不能自定义 allow/deny）
   - 合并 AgentSpec 的 allow/deny（如果配置）
   - 叠加 skills permissions（例如 sandbox 能力上限内的扩展）

4) Tool Runtime manifest
   - Agent API 调用 Tool Runtime `POST /internal/tools/manifest`
   - Tool Runtime 根据 `requested_tool_names`（允许 glob pattern）过滤工具集，并基于 policy/context 做 allow/deny
   - Tool Runtime 返回：
     - `tools[]`：最终注入给上游模型的 OpenAI function tools
       - 允许携带少量 AnyAgent 内部扩展字段（例如 `x-anyagent-kind: command`）用于 stage events 派生
       - 约束：这些扩展字段**不得**转发给上游模型（Agent API 会在注入前剥离）
     - `toolset_version`：当前 registry 版本号（用于 execute 的乐观一致性校验）

5) 上游模型调用工具 → Tool Runtime execute
   - Agent API 解析模型返回的 `function_call` items
   - 对每个 call 调用 Tool Runtime `POST /internal/tools/execute`，携带：
     - `toolset_version`（来自 manifest）
     - `context`（同一 run 内保持一致，除非显式演进）
   - Tool Runtime 返回 tool result，Agent API 将其封装成 `function_call_output` 再提交回上游模型继续 loop

## 3. 字段合约（Contract）

### 3.1 `requested_tool_names`

- 类型：`list[str] | null`
- 含义：本次 run “希望披露”的工具名（或 glob pattern）
- 约束：
  - v0 允许 pattern（例如 `app.*` / `sandbox.*` / `feishu.*`），由 Tool Runtime 展开/收口
  - 若 `requested_tool_names is None`，Tool Runtime manifest 按“默认全量”处理（仍受 policy/context 约束）

### 3.2 `context`

- 类型：`dict`
- 含义：Tool Runtime 执行与策略校验所需的上下文（trace/requester/channel/auth_ref/policy 等）
- 关键安全点：
  - caller 不能通过 `metadata.context.policy` 自定义工具 allow/deny（必须被服务端丢弃）
  - 服务端允许通过 AgentSpec 与 skills permissions 生成 policy hint（仍由 Tool Runtime 二次校验）

### 3.3 `toolset_version`

- 类型：`int`
- 含义：Tool Runtime 当前 tool registry 的版本号（随工具集变更递增）
- 用途：
  - Agent API 在 execute 时携带该版本号，Tool Runtime 会做一致性校验
  - 若版本不一致，Tool Runtime 返回 409 且 error.code=`toolset_version_mismatch`

## 4. 缓存与一致性（TTL cache + mismatch retry）

### 4.1 manifest TTL 缓存

Agent API 在内存里做短 TTL 缓存，减少同参数重复请求的 manifest I/O。

缓存 key（概念上）包含：
- `agent_id`
- `session_key`
- `enabled_skills`（stable_id 列表，排序后参与 key）
- `requested_tool_names`（排序后参与 key）
- `context`（以 sort_keys JSON 参与 key）

注意：
- v0 的实现是“短 TTL + 内存缓存”，适合单进程/单实例场景；多实例一致性由 `toolset_version` 机制兜底。

### 4.2 `toolset_version_mismatch` 单次重试

当 Tool Runtime execute 返回 409 且 code=`toolset_version_mismatch` 时：

1) Agent API 清空 manifest cache（避免继续使用旧版本）
2) 重新 fetch manifest，拿到新的 `tools[]` 与 `toolset_version`
3) 对**当前这一次 tool call** 重新 execute（只重试 1 次）

## 5. 内部可观测端点：`GET /internal/skills/list`

该端点用于 Gateway/UI 侧展示 skills 列表及其依赖工具（不做额外 I/O，数据来自 startup 加载缓存）：

- 输出字段包含：
  - `stable_id`/`name`/`description`/`short_description`/`scope`
  - `path`/`source_hash`（用于精确资源引用与审计）
  - `interface`（用于 UI/agent 默认提示与 catalog 渐进式披露）
  - `enabled`（基于 AgentSpec `disabled_paths` 中的 skill name 解析后计算）
  - `requested_tool_names`（来自 skill `dependencies.tools` 映射）
