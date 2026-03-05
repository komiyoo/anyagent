# tests/acceptance/storage（存储与回放验收）

面向 `apps/agent-api` 的离线 smoke 脚本，覆盖 rollout 持久化、轮转与回放一致性。

## 脚本

- `acceptance_rollout_storage_consistency_smoke.py`：none vs external 一致性（可选 external）
- `acceptance_rollout_rotation_smoke.py`：rollout 轮转与连续性
- `acceptance_rollout_replay_smoke.py`：replay 语义与写入门控相关约束

## 运行

```bash
uv run --project apps/agent-api python tests/acceptance/storage/acceptance_rollout_storage_consistency_smoke.py
uv run --project apps/agent-api python tests/acceptance/storage/acceptance_rollout_rotation_smoke.py
uv run --project apps/agent-api python tests/acceptance/storage/acceptance_rollout_replay_smoke.py
```

