# tests/acceptance/sdk（SDK/协议验收）

面向 `packages/anyagent` 的离线 smoke 脚本，覆盖 SDK 入口语义、协议解析与阶段事件衍生逻辑。

## 脚本

- `acceptance_anyagent_client_surface_smoke.py`
- `acceptance_command_stage_derivation_smoke.py`

## 运行

```bash
uv run --project packages/anyagent python tests/acceptance/sdk/acceptance_anyagent_client_surface_smoke.py
uv run --project packages/anyagent python tests/acceptance/sdk/acceptance_command_stage_derivation_smoke.py
```
