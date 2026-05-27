<!--
---
doc_kind: architecture
status: stable
tags: ["sdk", "client", "types", "control-plane", "stage-events", "docs"]
summary: AnyAgent SDK public surface, module ownership, typed model facade, and verification map.
req: ["requirements.md#req-4", "requirements.md#req-9"]
---
-->

# SDK Public Surface

本文档是 AnyAgent SDK 的长期维护入口。它只描述公开 surface、模块归属、repo 内引用和验证入口；字段级 wire contract 仍以 `anyagent.protocol.*` 和对应 Pydantic model 为真源。

## 1. 模块归属

| Surface | 真源 | 说明 |
|---|---|---|
| SDK 入口类 | `packages/anyagent/src/anyagent/agent_api_client.py` | `AnyAgent` resource namespace pattern，聚合 OpenAI 兼容面与 anyagent 超集面 |
| SDK public models | `packages/anyagent/src/anyagent/types/__init__.py` | 业务侧导入入口，重导出稳定模型 facade |
| Wire protocol | `packages/anyagent/src/anyagent/protocol/` | OpenAI 兼容、internal/admin API、Stage Events、observability、tool runtime 等协议 SSOT |
| 内置 server API | `packages/anyagent/src/anyagent/server/app.py` | `/v1/*`、`/internal/*`、`/admin/*` endpoint 实现 |
| CLI / workspace bootstrap | `packages/anyagent/src/anyagent/cli.py` | `anyagent init`、`doctor`、`serve`、`config init`、storage 命令 |

维护规则：

- 公开 SDK 输入/输出类型优先从 `anyagent.types` 暴露；业务文档不要要求调用方直接拼 `anyagent.protocol.*` 的内部模块路径。
- 新增 SDK namespace 或 helper 时，同步更新本文档、`docs/architecture/responses-api-sdk-and-server.md` 的主路径说明，以及 `todo/sdk.md` 的证据。
- 新增或修改 wire contract 时，先改 `anyagent.protocol.*`，再改 SDK facade、server endpoint 与测试。

## 2. SDK Namespace Map

| Namespace | 主要方法 | Server endpoint / 行为 | Typed result |
|---|---|---|---|
| `client.openai` / `client.async_openai` | OpenAI official SDK `responses.*` | `/v1/responses` | OpenAI SDK models |
| `client.responses` | `retrieve()` / `cancel()` | `/v1/responses/{id}` | dict / OpenAI-compatible payload |
| `client.events` | `list()` / `list_typed()` / `latest_prompt_context()` / `replay_summary()` / `stream_typed()` | `/internal/events/list`、`/internal/events/stream` | `InternalEventsListResponse`、`StageEvent`、`InternalEventsReplaySummary` |
| `client.observability` | `summary()` / `runs()` / `timeline()` / `metrics()` / `tools()` / `errors()` / `trace()` | `/internal/observability/*` | `InternalObservability*` models |
| `client.agents` | `list()` / `get()` | `/internal/agents` | `InternalAgentsListResponse`、`InternalAgentDetailResponse` |
| `client.skills` | `list()` | `/internal/skills/list` | `InternalSkillsListResponse` |
| `client.tools` | `catalog()` / `explain()` | `/internal/tools/catalog` + SDK-side composition | `InternalToolCatalogResponse`、`ToolVisibilityExplanation` |
| `client.prompts` | `preview()` / `example_run_bundle()` / `example_scenarios()` | `/internal/prompt/bundle` or local typed examples | `InternalPromptBundlePreviewResponse`、`PromptRunBundleExampleResponse` |
| `client.admin` | storage, plugins, credentials, workspace files, agent config, skill import/install/update, tool catalog | `/admin/*` | `Admin*` models and refs |
| `client.health()` | health check | `/healthz` | `HealthResponse` |

## 3. Public Model Facade

`anyagent.types` is the SDK-facing model entrypoint:

```python
from anyagent import AnyAgent
from anyagent.types import StageEvent, ToolVisibilityExplanation

client = AnyAgent(api_key="...", base_url="http://127.0.0.1:8787")
```

Facade 约束：

- `anyagent.types` 可以重导出 protocol model，但不重新定义 wire 字段。
- SDK 请求发送前与响应返回后都应做 Pydantic 边界校验。
- 文档示例里出现 SDK typed model 时，优先从 `anyagent.types` import。
- 面向 server/runtime 内部的实现文档可以引用 `anyagent.protocol.*`，但要说明它是 wire-level SSOT。

## 4. 文档系统引用

SDK 文档入口按用途分层：

- 总入口：[../README.md](../README.md)
- 架构入口：[README.md](README.md)
- Roadmap：[roadmap.md](roadmap.md)
- Responses + Server 泳道：[responses-api-sdk-and-server.md](responses-api-sdk-and-server.md)
- Stage Events 设计：[agent-api-client-stage-events.md](agent-api-client-stage-events.md)
- OpenAI-first ADR：[decisions/openai-first-api-surface.md](decisions/openai-first-api-surface.md)
- 测试策略：[testing-strategy.md](testing-strategy.md)
- 任务证据：`todo/sdk.md`

不要在 README、roadmap、TODO 和本文档之间复制同一段完整 API 说明。推荐分工：

- README：用户主路径和最短示例。
- Roadmap：阶段状态、剩余方向和关键里程碑。
- 本文档：SDK surface map、模块归属、引用入口。
- TODO：任务状态、需求锚点、实现证据和验证记录。
- Protocol / code：字段与行为真源。

## 5. 验证入口

最小验证按改动类型选择：

| 改动 | 命令 |
|---|---|
| 文档链接、manifest、TODO 证据 | `python3 scripts/docs/check.py --root . --check-manifest` |
| 文档 inline repo refs 大清理 | `python3 scripts/docs/check.py --root . --check-manifest --check-code-refs` |
| SDK/control-plane 离线 smoke | `bash scripts/ci/run_offline_smokes.sh` |
| SDK/server pytest 回归 | `bash scripts/ci/run_pytest_regressions.sh` |
| docs manifest 刷新 | `python3 scripts/docs/index.py --root .` |
| context pack 筛选 | `python3 scripts/docs/pack.py --root . --tags sdk` |

验收脚本和测试位置：

- `tests/unit/test_agent_api_client_control_plane.py`
- `tests/contract/test_events_sdk_contract.py`
- `tests/acceptance/sdk/acceptance_prompt_context_sdk_smoke.py`
- `tests/acceptance/server/acceptance_prompt_envelope_smoke.py`

