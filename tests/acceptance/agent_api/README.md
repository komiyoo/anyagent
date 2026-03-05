# tests/acceptance/agent_api（Agent API 验收）

面向 `apps/agent-api` 的离线 smoke 脚本，覆盖 session/runtime 行为与可选 endpoints。

## 脚本

- `acceptance_responses_smoke.py`：HTTP 直连 Responses API 基本兼容面（不依赖 OpenAI SDK）
- `acceptance_session_resume_smoke.py`：session resume + runtime_config merge 语义
- `acceptance_optional_responses_endpoints_smoke.py`：`GET /v1/responses/{id}` + `POST /v1/responses/{id}/cancel`（可选）

## 运行

```bash
uv run --project apps/agent-api python tests/acceptance/agent_api/acceptance_responses_smoke.py
uv run --project apps/agent-api python tests/acceptance/agent_api/acceptance_session_resume_smoke.py
uv run --project apps/agent-api python tests/acceptance/agent_api/acceptance_optional_responses_endpoints_smoke.py
```
