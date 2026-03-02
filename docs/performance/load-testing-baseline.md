# 压测场景与容量指标口径（v0）

对应需求：`requirements.md#req-7`

本文用于把“怎么压测、看什么指标、如何解读结果”固化为一套 **可复现** 的基线口径，避免不同人/不同环境下得出不可比较的结论。

## 1. 目标与非目标

目标：
- 给出 v0 的最小压测场景集合（覆盖 `/v1/responses` 流式/非流式、跨会话并行、会话内串行的关键路径）
- 给出容量指标口径（延迟、吞吐、资源、错误、排队）与采集建议

非目标：
- 不在本文中承诺一个固定的“QPS 数字”（受机器/模型/网络/工具/缓存命中率影响）
- 不强制引入 APM/指标系统（先把场景与口径写清）

## 2. 被测接口与维度

### 2.1 Agent API（必测）

- `POST /v1/responses`（`stream=false`）
- `POST /v1/responses`（`stream=true`，SSE）

维度（每个场景都要明确）：
- `agent_id`：固定为 `main` 或指定
- `session_key`：是否提供；提供时要指定分布（单会话 vs 多会话）
- `stream`：是否流式
- 是否触发 tool call（若无法稳定触发，可先压“无工具”基线，再补工具场景）

### 2.2 Tool Runtime（建议测）

- `POST /internal/tools/manifest`
- `POST /internal/tools/execute`

说明：
- Tool Runtime 的性能会直接影响 agent loop 的尾延迟（尤其是 tool call 场景）。

## 3. 场景定义（推荐最小集合）

### S1：跨会话并行基线（验证并行度）

目的：验证“会话间并行”成立，且不会被 `session_key` 缺失导致误串行化。

配置建议：
- 并发 `C = 20/50/100`
- `session_key`：每个请求不同（例如 `loadtest::{i}`）
- `stream=false`

观测：
- p50/p95/p99 延迟
- 5xx 比例
- Agent API 进程 CPU / RSS

### S2：会话内串行基线（验证 keyed serialization）

目的：验证同一 `session_partition_key` 内请求严格串行（不会并发执行 agent loop）。

配置建议：
- 并发 `C = 10/20`
- 固定 `session_key` 为同一个值（例如 `loadtest::single_session`）
- `stream=false`

观测：
- 延迟应近似呈线性排队（单请求耗时 * 并发深度）
- 5xx 比例

### S3：流式 SSE 基线（验证慢消费者不会放大内存）

目的：验证 `/v1/responses?stream=true` 走 pull-based streaming，不预缓冲大量上游事件；慢消费者时不会导致 Agent API 内存持续增长。

配置建议：
- 并发 `C = 10/20`
- `stream=true`
- 客户端侧刻意“慢读”（例如读取 SSE 时 sleep / 限速），模拟慢消费者

观测：
- Agent API RSS 是否随时间持续上升（不应线性增长）
- 连接数与 fd 占用

### S4：工具调用场景（可选，建议后续补齐）

目的：覆盖 manifest/execute 的真实闭环。

配置建议：
- 并发 `C = 10/20`
- `stream=false` 与 `stream=true` 各压一遍
- 需要一个可控、低外部依赖的 tool（例如 `app.echo`/`core.noop`）。若当前仅有外部 I/O 工具（如 `core.web_fetch`），建议先补一个 deterministic tool 再做该场景。

观测：
- Tool Runtime 的 p95/p99 latency
- `toolset_version_mismatch` 重试比例（应极低；出现时应自动恢复）

## 4. 指标口径（必须统一）

### 4.1 延迟（Latency）

- `p50/p95/p99`：以客户端观测为准（端到端）
- 对 `stream=true`：
  - TTFT（time to first token/event）：首个 SSE event 到达时间
  - TTFCompleted：`response.completed` 到达时间

### 4.2 吞吐（Throughput）

- RPS：请求/秒（按场景统计）
- 对 `stream=true`：同时记录平均连接数与 bytes/sec

### 4.3 错误（Errors）

- HTTP 4xx/5xx 比例
- 典型错误分类：
  - 上游模型错误（OpenAI / proxy）
  - Tool Runtime manifest/execute 错误
  - 超时/断连

### 4.4 资源（Resources）

- CPU（平均与峰值）
- RSS（内存）
- fd/连接数（尤其是 SSE）

### 4.5 排队（Queueing）

- 同会话（同 `session_partition_key`）串行排队深度（若未埋点，可用延迟线性增长侧推）

## 5. 可复现执行建议（示例）

说明：以下命令仅作示意，按你本机端口与鉴权配置替换。

- 非流式压力（多会话）：
  - 使用 `hey`/`wrk`/自写脚本，确保每个请求携带不同 `metadata.session_key`
- 流式压力（慢读）：
  - 使用自写脚本连接 SSE，读取一行后 sleep（例如 50ms～200ms），模拟慢消费者

## 6. 结果记录模板（建议）

每次压测至少记录：
- Git SHA / 分支
- 机器信息（CPU/内存）
- 并发参数（C、持续时间、session_key 分布）
- p50/p95/p99、错误率、CPU/RSS、连接数
- 关键结论（瓶颈点/回归点）

