# 并发与可靠性 TODO

对应需求：`requirements.md#req-7`

## 目标

- 在多实例部署下实现“会话内串行、跨会话并行”，并提供可靠的重试/去重/慢消费者治理能力。

## 里程碑（Milestones）

- M1：按 `session_partition_key` keyed serialization 生效
- M2：幂等 + 事件补发/断线恢复
- M3：压测与容量基线

## 任务（Tasks）

- [ ] P0 定义并实现 keyed serialization 的并发分片策略（Req: `requirements.md#req-7`）
- [ ] P1 定义 backpressure/慢消费者治理策略（SSE/WS）并实现（Req: `requirements.md#req-7`）
- [ ] P2 制定压测场景与容量指标口径（Req: `requirements.md#req-7`）

