# tests/acceptance/sdk（SDK/协议验收）

面向 `packages/anyagent` 的离线 smoke 脚本，覆盖 SDK 入口语义、协议解析与阶段事件衍生逻辑。

## 脚本

- `acceptance_anyagent_client_surface_smoke.py`
- `acceptance_command_stage_derivation_smoke.py`
- `acceptance_stage_event_trace_id_smoke.py`
- `acceptance_events_replay_done_persisted_smoke.py`
- `acceptance_prompt_context_sdk_smoke.py`
- `acceptance_tool_credential_injection_smoke.py`
- `acceptance_exec_output_truncation_smoke.py`
- `acceptance_credential_audit_smoke.py`

## 运行

```bash
uv run --project packages/anyagent python tests/acceptance/sdk/acceptance_anyagent_client_surface_smoke.py
uv run --project packages/anyagent python tests/acceptance/sdk/acceptance_command_stage_derivation_smoke.py
uv run --project packages/anyagent python tests/acceptance/sdk/acceptance_stage_event_trace_id_smoke.py
uv run --project packages/anyagent python tests/acceptance/sdk/acceptance_events_replay_done_persisted_smoke.py
uv run --project packages/anyagent python tests/acceptance/sdk/acceptance_prompt_context_sdk_smoke.py
uv run --project packages/anyagent python tests/acceptance/sdk/acceptance_tool_credential_injection_smoke.py
uv run --project packages/anyagent python tests/acceptance/sdk/acceptance_exec_output_truncation_smoke.py
uv run --project packages/anyagent python tests/acceptance/sdk/acceptance_credential_audit_smoke.py
```
