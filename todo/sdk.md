# SDK TODO

对应需求：`requirements.md#req-4`

## 目标

- 把 SDK / built-in server / agent runtime 的上下文编排收敛成可缓存、可审计、可按需注入的一套稳定机制

## 里程碑（Milestones）

- M1：定义 `PromptEnvelope` / `ContextFragment` / `prompt_cache_key` 协议并补 catalog 字段
- M2：收口 AGENTS / skills / environment / MCP 注入路径，稳定 prefix cache
- M3：补 replay / audit / compaction / acceptance 闭环

## 任务（Tasks）

- [x] P3 补齐配置化 workspace CLI 入口：新增 `anyagent init` 生成最小 `.agents/` workspace，新增 `anyagent doctor` 离线体检 agent pack、skills、MCP command/cwd、main exposed 与 opensandbox 可用性，并用真实 `init -> doctor -> serve -> /healthz` 闭环验证配置开箱启动（Req: `requirements.md#req-2-1`，`requirements.md#req-2-2`，`requirements.md#req-4`；Impl: `packages/anyagent/src/anyagent/cli.py:79`，`tests/unit/test_cli_workspace_commands.py:1`，`README.md:24`；Module: `sdk-cli`）
- [x] P0 冻结 context engineering 设计口径，并将工作区草案回收到仓库内真源（Req: `requirements.md#req-2-1-1`；Design: `docs/architecture/skills-tool-runtime-interaction.md:1`、`docs/architecture/responses-api-sdk-and-server.md:113`；Impl: `requirements.md:157`、`docs/architecture/skills-tool-runtime-interaction.md:7`、`docs/architecture/responses-api-sdk-and-server.md:113`；Module: `sdk-context`）
- [x] P0 定义统一 `PromptEnvelope` / `ContextFragment` 协议与 renderer（Req: `requirements.md#req-2-1-1`、`requirements.md#req-12-6`；Impl: `packages/anyagent/src/anyagent/protocol/context_fragments.py:14`、`packages/anyagent/src/anyagent/agent_runtime/prompt_envelope.py:17`；Module: `agent_runtime`）
- [x] P0 为 `/internal/skills/list` 补齐 `path/interface/source_hash` 等 catalog 字段（Req: `requirements.md#req-12-7`；Impl: `packages/anyagent/src/anyagent/protocol/agent_api_internal.py:80`、`packages/anyagent/src/anyagent/server/runtime.py:173`；Module: `server`）
- [x] P1 将 `AGENTS.md`、selected skills、environment context 改为统一结构化片段注入（Req: `requirements.md#req-2-1-1`、`requirements.md#req-12-6-2`；Impl: `packages/anyagent/src/anyagent/agent_runtime/prompt_injection.py:7`、`packages/anyagent/src/anyagent/agent_runtime/skills_injection.py:19`；Module: `agent_runtime`）
- [x] P1 新增稳定 `prompt_cache_key`，与现有 manifest cache 分层（Req: `requirements.md#req-5-2`、`requirements.md#req-12-8`；Impl: `packages/anyagent/src/anyagent/agent_runtime/prompt_envelope.py:113`；Module: `agent_runtime`）
- [x] P1 让 provider adapter 基于 `PromptEnvelope` 做 role 映射，而不是在 server/app/tool_loop 中各自拼接（Req: `requirements.md#req-4`；Impl: `packages/anyagent/src/anyagent/server/app.py:341`、`packages/anyagent/src/anyagent/agent_runtime/tool_loop.py:372`；Module: `server`）
- [x] P2 补齐 replay / audit 对 contextual fragments 的识别与 SDK 调试消费闭环（Req: `requirements.md#req-4`、`requirements.md#req-12-8`；Impl: `packages/anyagent/src/anyagent/protocol/stage_events.py:257`、`packages/anyagent/src/anyagent/protocol/agent_api_internal.py:46`、`packages/anyagent/src/anyagent/agent_api_client.py:154`、`tests/unit/protocol/test_internal_events_list_response.py:1`、`tests/contract/test_events_sdk_contract.py:1`、`tests/acceptance/sdk/acceptance_prompt_context_sdk_smoke.py:1`；Module: `sdk-context`）
- [x] P2 补齐 compaction 对 contextual fragments 的识别、压缩与更高层 replay 消费链路（Req: `requirements.md#req-4`、`requirements.md#req-12-8`；Impl: `packages/anyagent/src/anyagent/protocol/stage_events.py:296`、`packages/anyagent/src/anyagent/agent_runtime/prompt_envelope.py:174`、`packages/anyagent/src/anyagent/protocol/agent_api_internal.py:74`、`packages/anyagent/src/anyagent/agent_api_client.py:187`、`tests/unit/protocol/test_prompt_context_audit.py:1`、`tests/acceptance/sdk/acceptance_prompt_context_sdk_smoke.py:1`；Module: `sdk-context`）
- [x] P3 将 `PromptEnvelope`、`PromptContextAudit`、session snapshot prompt context 上提为 protocol typed models，并让 runtime/server/SDK 统一消费（Req: `requirements.md#req-4`、`requirements.md#req-12-8`；Impl: `packages/anyagent/src/anyagent/protocol/prompt_context.py:1`、`packages/anyagent/src/anyagent/protocol/session_snapshot.py:1`、`packages/anyagent/src/anyagent/agent_runtime/prompt_envelope.py:1`、`packages/anyagent/src/anyagent/agent_runtime/session_runtime.py:1`、`tests/unit/protocol/test_session_snapshot.py:1`；Module: `sdk-context`）
- [x] P3 将 AGENTS 加载先收敛为 `workspace + agent-pack` 两层，并为 provider 不支持 `developer` role 的场景补齐 `instruction_role=system` 退化路径（Req: `requirements.md#req-2-1-1`；Impl: `packages/anyagent/src/anyagent/agent_packs.py:65`、`packages/anyagent/src/anyagent/agent_runtime/prompt_envelope.py:20`、`tests/unit/agent_runtime/test_prompt_envelope.py:108`；Module: `sdk-context`）
- [x] P3 为 prompt explain/debug 补齐完整 bundle 预览：新增 `POST /internal/prompt/bundle`，可返回 rendered fragments、manifest tools、tool context、`effective_body` 与 `applied_body`（Req: `requirements.md#req-4`、`requirements.md#req-12-8`；Impl: `packages/anyagent/src/anyagent/protocol/agent_api_internal.py:1`、`packages/anyagent/src/anyagent/server/app.py:1`、`tests/acceptance/server/acceptance_prompt_envelope_smoke.py:1`；Module: `server`）
- [x] P3 当 sandbox 启用且 `exec` 真正可见时，自动注入 `sandbox_guidance` fragment，并把 `mcp_server_ref` 收进 `PromptEnvelope` 稳定前缀（Req: `requirements.md#req-5`、`requirements.md#req-12-8`；Impl: `packages/anyagent/src/anyagent/protocol/context_fragments.py:1`、`packages/anyagent/src/anyagent/agent_runtime/prompt_envelope.py:1`、`tests/unit/agent_runtime/test_prompt_envelope.py:1`、`tests/acceptance/server/acceptance_prompt_envelope_smoke.py:1`；Module: `sdk-context`）

## 阶段进展（2026-03-13）

- 已实现一版 `PromptEnvelope` / `ContextFragment` 主干，当前落点：`packages/anyagent/src/anyagent/agent_runtime/prompt_envelope.py`、`packages/anyagent/src/anyagent/protocol/context_fragments.py`；当前状态：已实现、待更完整 provider/integration 验证
- 已将 `AGENTS.md`、selected skills、`environment_context` 注入改为结构化 fragment 渲染，并让 built-in server 在进入 tool loop 前统一应用 envelope：`packages/anyagent/src/anyagent/agent_runtime/prompt_injection.py`、`packages/anyagent/src/anyagent/agent_runtime/skills_injection.py`、`packages/anyagent/src/anyagent/server/app.py`、`packages/anyagent/src/anyagent/agent_runtime/tool_loop.py`
- 已扩展 `/internal/skills/list` catalog 字段：`path` / `source_hash` / `interface`，当前落点：`packages/anyagent/src/anyagent/protocol/agent_api_internal.py`、`packages/anyagent/src/anyagent/server/runtime.py`
- 已补 provider 级最小闭环：首轮请求可见 `prompt_cache_key` 与结构化 `environment_context`，并且 tool follow-up body 保留 `prompt_cache_key`
- 已补最小 replay / audit 持久化抓手：内部事件 `anyagent.prompt.context` 与 session snapshot `last_run.prompt_context` 已落盘，当前落点：`packages/anyagent/src/anyagent/protocol/stage_events.py`、`packages/anyagent/src/anyagent/agent_runtime/session_runtime.py`、`packages/anyagent/src/anyagent/server/app.py`
- 已补 SDK replay/debug 消费面：`/internal/events/list` 返回值现在可直接 `typed_events()` / `latest_prompt_context()`，并新增 `client.events.list_typed()` / `client.events.latest_prompt_context()`，当前落点：`packages/anyagent/src/anyagent/protocol/agent_api_internal.py`、`packages/anyagent/src/anyagent/agent_api_client.py`
- 已补 prompt context compaction 与更高层 replay 摘要：`anyagent.prompt.context` / session snapshot 统一复用 compacted audit metadata，并新增 `client.events.replay_summary()`，当前落点：`packages/anyagent/src/anyagent/protocol/stage_events.py`、`packages/anyagent/src/anyagent/agent_runtime/prompt_envelope.py`、`packages/anyagent/src/anyagent/protocol/agent_api_internal.py`、`packages/anyagent/src/anyagent/agent_api_client.py`
- 已将 `PromptEnvelope` / `PromptContextAudit` / `PersistedSessionSnapshot` 收口到 protocol typed models，当前落点：`packages/anyagent/src/anyagent/protocol/prompt_context.py`、`packages/anyagent/src/anyagent/protocol/session_snapshot.py`
- 已补 prompt bundle explain/debug 入口：`POST /internal/prompt/bundle` 现在会返回 rendered fragments、tool manifest 与 applied body，可直接查看一次 run 的上下文产物
- 已补 `sandbox_guidance` 与 `mcp_server_ref` fragment：当前 `PromptEnvelope` 稳定前缀已不止 AGENTS，还会在条件满足时自动收进沙箱引导与 MCP catalog 片段
- 已补最小静态验证：`uv run python -m py_compile packages/anyagent/src/anyagent/agent_runtime/__init__.py packages/anyagent/src/anyagent/agent_runtime/prompt_envelope.py packages/anyagent/src/anyagent/agent_runtime/prompt_injection.py packages/anyagent/src/anyagent/agent_runtime/skills_injection.py packages/anyagent/src/anyagent/agent_runtime/tool_loop.py packages/anyagent/src/anyagent/server/app.py packages/anyagent/src/anyagent/server/runtime.py packages/anyagent/src/anyagent/protocol/__init__.py packages/anyagent/src/anyagent/protocol/agent_api_internal.py packages/anyagent/src/anyagent/protocol/context_fragments.py tests/unit/agent_runtime/test_prompt_envelope.py tests/acceptance/server/acceptance_skills_list_smoke.py`
- 已补最小消费验证：`uv run --with-editable ./packages/anyagent python tests/acceptance/sdk/acceptance_prompt_context_sdk_smoke.py` → `ok: acceptance_prompt_context_sdk_smoke`
- 已补正式 pytest 回归入口：`scripts/ci/run_pytest_regressions.sh`，当前已验证 `tests/unit`、`tests/contract`、`tests/integration` 与 targeted server acceptance pytest 可运行

## 决策 & 争议点

- [x] `PromptEnvelope` 放在 `anyagent.protocol`，runtime/server 只消费与映射 typed model（关联：`requirements.md#req-4`）
- [x] `AGENTS.md` 先冻结为 `workspace + agent-pack` 两层，后续如引入更多 roots 再单独扩展（关联：`requirements.md#req-2-1-1`）
- [x] provider 不支持 `developer` role 时，统一通过 `instruction_role="system"` 退化（关联：`requirements.md#req-2-1-1`）

## 参考

- `requirements.md`
- `docs/architecture/skills-tool-runtime-interaction.md`
- `docs/architecture/responses-api-sdk-and-server.md`
