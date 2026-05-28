# Server Runtime TODO

对应需求:`requirements.md#req-5`、`requirements.md#req-4-3`

## 目标

- 让 Python reference server 在单机主路径稳定的基础上,具备多节点 / 多 workspace 的运行能力,并保持 contract 可替换。

## 当前事实

- Server 入口:`packages/anyagent/src/anyagent/server/app.py`
- Agent loop:`packages/anyagent/src/anyagent/agent_runtime/`
- Gateway / session 路由:`packages/anyagent/src/anyagent/gateway/`
- Session / Run / Event 抽象:`anyagent.protocol.*` + `anyagent.storage`
- 长期架构:`docs/architecture/runtime/stateless-agent-service-architecture.md`

## 里程碑

- M1:跨节点 Run 调度 & lock contract 实装
- M2:Observability 统一 envelope 出口
- M3:第二 server runtime(异语言)通过 reference conformance suite(Phase 4)

## 任务

### Phase 1.5 — Agentic Ecosystem Hardening

- [ ] P0 Skill → Agent Loop 注入管道:在 `agent_runtime` 增加 `SkillInjector`,负责解析用户输入中的 skill mention → 读取 SKILL.md → 注入到 prompt context,带可配置 token budget(Req: `requirements.md#req-5`)
- [ ] P1 配置层级 merge:支持 system(`/etc/anyagent/`) → user(`~/.anyagent/`) → workspace(`.anyagent/`) → session(CLI override) 的配置合并策略,workspace 层有安全 denylist(Req: `requirements.md#req-5`)
- [ ] P1 MCP 生命周期 Stage Events:对齐 `anyagent.protocol.events` 发射 `mcp.server.starting` / `mcp.server.ready` / `mcp.server.failed` 事件,可被 SDK 消费(Req: `requirements.md#req-5`、`requirements.md#req-5-13`)
- [ ] P2 AGENTS.md 层级遍历:支持从 cwd 到 project root 每层收集 AGENTS.md,拼接后注入 agent instructions,带 byte budget 限制(monorepo 场景)(Req: `requirements.md#req-5`)

### Phase 2 — Production Runtime Hardening

- [ ] P0 设计跨节点 Run 调度与 lock contract,落 ADR(Req: `requirements.md#req-5`)
- [ ] P0 实装 lock contract 的 Redis 与 PostgreSQL adapter,跑通跨节点 resume / cancel(Req: `requirements.md#req-5`、`requirements.md#req-3-1`)
- [ ] P1 统一 observability envelope 出口,接入 audit sink(Req: `requirements.md#req-5-13`)
- [ ] P2 整理 reference conformance suite,为第二 server runtime 接入准备验收基线(Req: `requirements.md#req-5`、`requirements.md#req-7`)

## 决策 & 争议点

- [ ] 跨节点 lock 的底座选择:Redis-only vs storage-agnostic vs 二者皆支持
- [ ] Observability envelope:OTel 直接对接 vs 仓内中间层 + 多 sink 适配

## 参考

- `docs/architecture/overview/roadmap.md` Phase 2 / Phase 4
- `docs/architecture/runtime/stateless-agent-service-architecture.md`
- `docs/architecture/runtime/agent-server-runtime-entities.md`
- `docs/architecture/control-plane/studio-control-plane-and-observability.md`
