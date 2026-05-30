## <!--

doc_kind: architecture
status: stable
tags: ["model-provider", "responses-api", "tools", "provider-registry"]
summary: 记录 OpenAI Responses API body 到 Anthropic/Gemini vendor API 的统一翻译层、能力裁决和路由 registry。

---

-->

# Model Provider Translators

需求锚点：`requirements.md#req-4`、`requirements.md#req-4-5`

## 边界

anyagent 的 agent loop 只依赖 `ModelProvider` 三方法，输入仍是 OpenAI Responses API compatible `body: dict`，输出仍是 OpenAI SDK `Response` model。OpenAI provider 保持直透 OpenAI-compatible Responses API，不进入翻译宿主。

Anthropic Messages 与 Google Gemini 走统一翻译层：

- 宿主：`packages/anyagent/src/anyagent/agent_runtime/model_providers/_translating_provider.py`
- 能力声明：`packages/anyagent/src/anyagent/agent_runtime/model_providers/_capabilities.py`
- 翻译 DTO/Protocol：`packages/anyagent/src/anyagent/agent_runtime/model_providers/_translation.py`
- 会话 state / idempotency：`packages/anyagent/src/anyagent/agent_runtime/model_providers/_conversation_state.py`
- HTTP 错误归一化：`packages/anyagent/src/anyagent/agent_runtime/model_providers/vendor_http.py`

Vendor-specific 文件只保留 settings、translator 与 factory：

- Anthropic：`packages/anyagent/src/anyagent/agent_runtime/model_providers/anthropic_messages.py`
- Gemini：`packages/anyagent/src/anyagent/agent_runtime/model_providers/google_gemini.py`

## 工具名 SSOT

模型可见工具名统一来自协议层：

- `model_tool_name_for_name(name, max_len=...)`
- `build_model_tool_name_map(tools, max_len=...)`

Anthropic 传 `max_len=128`，Gemini 传 `max_len=64`。translator 通过 `ToolNameMapping` 拿到 `source_to_model` / `model_to_source`，不再维护私有工具名规范化逻辑。

## 能力裁决

能力缺口在宿主按逐次请求 body 裁决：

- `tools` 非空但 provider 不支持 tools：抛 `ModelProviderInvalidRequestError`
- `tool_choice="required"` 但 provider 不支持 required：抛 `ModelProviderInvalidRequestError`
- named tool choice 但 provider 不支持 named：抛 `ModelProviderInvalidRequestError`
- `temperature` / `top_p` 不支持：从上游 payload 静默降级移除
- `max_output_tokens` 超 provider cap：clamp 到 cap

当前 Anthropic 与 Gemini 均支持工具调用与 required/named tool choice，均通过宿主使用伪流式 created/completed 事件。

## Anthropic 映射

- `tool_choice="required"` 映射为 `{"type": "any"}`
- named tool choice 映射为 `{"type": "tool", "name": <model_name>}`
- `tools[]` 映射为 Anthropic `tools[]`，schema 放入 `input_schema`
- `body.instructions` 与 `body.input` 中的 `developer` / `system` 消息合并为顶层 `system`
- `tool_use` block 映射回 Responses `function_call`
- Responses `function_call_output` 映射为 Anthropic `tool_result`

## Gemini 映射

- `tools[]` 映射为 `tools: [{"functionDeclarations": [...]}]`
- `tool_choice` 映射为 `toolConfig.functionCallingConfig`
  - `auto` -> `AUTO`
  - `none` -> `NONE`
  - `required` -> `ANY`
  - named -> `ANY` + `allowedFunctionNames`
- `body.instructions` 与 `developer` / `system` 消息合并为 `systemInstruction`
- Gemini `functionCall.args` object 序列化为 Responses `arguments` JSON 字符串
- Responses `function_call_output` 映射为 `functionResponse`，其 `name` 来自会话内已记录的 `call_id -> model_name`

## 路由 Registry

Provider 路由统一由 `packages/anyagent/src/anyagent/agent_runtime/model_providers/registry.py` 管理：

- env 默认 provider：`model_providers.get_default_model_provider()`
- workspace selection：`model_config.model_provider_for_selection()`
- CLI `models.yaml` 模板：`cli._render_models_yaml()`

新增 provider 时需要新增 registry spec 与 vendor translator/settings/factory；路由入口不再新增 if/elif 分支。

## 验证

单元覆盖：

- `tests/unit/agent_runtime/model_providers/test_translating_provider_shell.py`
- `tests/unit/agent_runtime/model_providers/test_capabilities.py`
- `tests/unit/agent_runtime/model_providers/test_anthropic_translator.py`
- `tests/unit/agent_runtime/model_providers/test_gemini_translator.py`
- `tests/unit/agent_runtime/model_providers/test_provider_registry.py`
- `tests/unit/protocol/test_tool_manifest_extensions.py`

最小回归命令：

```bash
cd packages/anyagent
uv run pytest ../../tests/unit/agent_runtime/model_providers/ ../../tests/unit/protocol/test_tool_manifest_extensions.py ../../tests/unit/test_model_config.py ../../tests/unit/test_cli_workspace_commands.py -q
```
