<!--
---
doc_kind: architecture
status: historical
tags: ["model-provider", "responses-api", "historical"]
summary: 历史记录。自研 Anthropic/Gemini HTTP translator 已删除；Responses 热路径经 pydantic-ai。
req: ["requirements.md#req-4", "requirements.md#req-4-5", "requirements.md#req-4-7"]
---
-->

# Model Provider Translators（历史）

本文是 **历史** 记录。自研 Anthropic Messages / Google Gemini / OpenAI Chat Completions HTTP translator 已从仓库删除。

当前执行面见 [agent-loop.md](../runtime/agent-loop.md)。`.anyagent/anyagent.yaml` 的 `models.providers.*.kind` 由 `packages/anyagent/src/anyagent/config/models.py` 解析，再在 `packages/anyagent/src/anyagent/agent_runtime/loop/models.py` 转成 pydantic-ai 模型字符串。

离线 smoke 仍可 patch `get_default_model_provider()`（OpenAI Responses 协议缝）。

现行口径见 [pydantic-ai loop + Langfuse ADR](../decisions/pydantic-ai-loop-and-langfuse.md#执行面替换范围)。

需求锚点：`requirements.md#req-4`、`requirements.md#req-4-5`、`requirements.md#req-4-7`

## 还保留什么

- `ModelProvider` 协议与错误类型：`packages/anyagent/src/anyagent/agent_runtime/model_providers/base.py`
- OpenAI Responses 默认工厂（测试注入缝）：`packages/anyagent/src/anyagent/agent_runtime/model_providers/openai_responses.py`
- kind 目录：`packages/anyagent/src/anyagent/config/models.py`

## 工具名

模型可见工具名仍来自协议层 `model_tool_name_for_name` / `build_model_tool_name_map`。vendor 侧长度限制由 pydantic-ai profile 处理，不再由自研 translator 裁决。

## 验证

```bash
uv run --project packages/anyagent pytest tests/unit/agent_runtime/model_providers/ tests/unit/agent_runtime/test_pydantic_ai_loop.py tests/unit/test_model_config.py tests/unit/cli/ -q
```
