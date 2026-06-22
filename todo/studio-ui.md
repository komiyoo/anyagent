# Studio UI Optimization TODO

对应需求: `requirements.md#req-14`、`requirements.md#req-4`

## 目标

将 AnyAgent Studio 从"功能原型"升级为"生产级高密度数据控制台"，提升信息密度、一致性和用户体验。

## 当前状态

- 已完成功能清单盘点: `docs/architecture/control-plane/studio-pages-inventory.md`
- 已完成优化设计方案: `docs/architecture/control-plane/studio-ui-optimization-plan.md`
- 15 个页面文件，~3660 行代码
- 所有页面基础功能已实现，待优化 UI 密度与交互体验

## 当前事实

- Studio 源码: `packages/anyagent/studio/src/`
- 页面组件: `packages/anyagent/studio/src/pages/`
- Hooks: `packages/anyagent/studio/src/hooks/`
- Client: `packages/anyagent/studio/src/anyagentClient.ts`
- 设计文档: `docs/architecture/control-plane/studio-*.md`

## 里程碑

- M1: 功能清单与优化方案文档化 ✅
- M2: 设计系统基础（核心组件库） ✅
- M3: 核心页面重构（Observability/Sessions/Home）
- M4: TypeScript SDK 迁移
- M5: 图表可视化与高级功能

## 任务

### Phase 1: 设计系统基础（1 周）

- [x] P0 创建 `components/design-system/` 目录结构（Req: `requirements.md#req-14`）
- [x] P0 实现 StatStrip 组件替代 Metric Card（Req: `requirements.md#req-14`）
- [x] P0 实现 CompactTable 组件（32-36px 行高）（Req: `requirements.md#req-14`）
- [x] P0 实现 CollapsibleSection 组件（默认折叠）（Req: `requirements.md#req-14`）
- [x] P0 实现 StatusBadge 组件（紧凑徽章）（Req: `requirements.md#req-14`）
- [x] P0 实现 LoadingStates（Skeleton/Spinner/Progress）（Req: `requirements.md#req-14`）
- [x] P0 实现 ErrorBanner 与 Toast 组件（Req: `requirements.md#req-14`）
- [x] P0 更新 `styles.css` 颜色系统与 typography（Req: `requirements.md#req-14`）

### Phase 2: 核心页面重构（2 周）

- [x] P0 Observability 页面完整重构（示范页面，首屏 8-10 条 run）（Req: `requirements.md#req-14`）
- [x] P0 Sessions 页面优化（紧凑表格，stat-strip 聚合）（Req: `requirements.md#req-14`）
- [x] P0 Home 页面优化（Use/Build 模式差异化）（Req: `requirements.md#req-14`）
- [x] P1 Configure 页面优化（panels 紧凑网格）（Req: `requirements.md#req-14`）
- [x] P1 Tools 页面优化（双列布局，紧凑表格）（Req: `requirements.md#req-14`）
- [x] P1 Credentials 页面优化（紧凑表格，侧边栏表单）（Req: `requirements.md#req-14`）
- [x] P1 Settings 页面优化（紧凑表单，stat-strip health）（Req: `requirements.md#req-14`）

### Phase 3: 次要页面与功能（2 周）

- [x] P1 Skills 页面优化（紧凑网格，metadata 折叠）（Req: `requirements.md#req-14`）
- [x] P1 MCP 页面优化（紧凑列表，侧边栏编辑）（Req: `requirements.md#req-14`）
- [x] P1 Files 页面优化（全屏编辑器，侧边栏文件列表）（Req: `requirements.md#req-14`）
- [x] P1 Debug 页面优化（紧凑 event 列表，折叠 JSON）（Req: `requirements.md#req-14`）
- [x] P1 Audit 页面优化（紧凑表格，内联过滤）（Req: `requirements.md#req-14`）
- [x] P1 Evaluations 页面优化（紧凑列表，内联对比）（Req: `requirements.md#req-14`）
- [x] P1 Prompts 页面优化（紧凑版本列表，并排 diff）（Req: `requirements.md#req-14`）
- [x] P1 实时数据与缓存：SSE 连接管理 + SWR 缓存策略（Req: `requirements.md#req-14`）
  - 决策：SSE 已由 `useEventStream` 提供；新增 Observability runs 自动轮询（运行中 5s / 空闲 10s + visibility 暂停，方案 §4.4）。未引入独立 SWR 抽象——现有 hooks 已用 useMemo 缓存计算结果，新增抽象收益低于风险。
- [ ] P1 虚拟滚动大列表（runs/events/timeline 100+ 行）（Req: `requirements.md#req-14`）
  - 决策：暂缓。当前所有列表已用 `.slice(0, N)` 截断（runs ≤20、events ≤20、timeline ≤20），无 100+ 行实际场景；引入 `@tanstack/react-virtual` 需新依赖且 CompactTable 需改造，收益不抵成本。待真实出现长列表再启用。
- [ ] P1 性能优化：React.memo + useMemo + 请求取消（Req: `requirements.md#req-14`）
  - 决策：部分完成。hooks 已普遍 useMemo；请求取消需改 `fetchJson` 签名（协议级，影响所有 API），风险高，留待 Phase 4 SDK 迁移时统一处理。React.memo 对多 props 页面易失效，暂不添加。

### Phase 4: TypeScript SDK 迁移（1 周）

- [x] P1 迁移到 `@anyagent/sdk`，替换 `anyagentClient.ts` 类型（Req: `requirements.md#req-4`）
  - 完成：Studio 声明对 TS SDK 的 `file:` 依赖（`anyagent@0.3.0`，symlink 本地 `sdks/typescript`）；新增 `src/sdk/typeAlignment.ts` 编译期校验，证明 SDK wire 类型与 Studio UI 类型结构兼容（ObservabilityRunItem 双向等价，其余 UI 类型为 SDK 类型的子集）。
  - 决策：未全量 re-export SDK 类型——Studio 类型是面向 UI 的组合/派生形态（如 `AgentDetail = AgentSummary & {...}`），SDK 是 wire-level，职责不同，强行对齐会破坏 UI 层表达。类型对齐校验已提供迁移信心基础。
- [ ] P1 消费 SDK `client.responses.stream()` SSE 方法（Req: `requirements.md#req-4`）
  - 决策：延后。Studio 的 `runChat`/`streamPersistedEvents` 含 SSE 解析、消息累积、stage event 分类等业务逻辑，SDK `responses.create` 未提供等价的流式回调 API，需逐函数核对行为，风险高。
- [~] P1 消费 SDK sessions/observability namespace（Req: `requirements.md#req-4`）
  - 完成：`loadObservabilityRuns` 已改走 `client.observability.runs()`（动态 import 懒加载 SDK，独立 chunk 337KB，主 bundle 不膨胀），对外签名与返回类型零破坏，作为逐函数迁移模板。
  - 决策：其余 `loadObservability*`/`loadSessions*` 等函数迁移延后——需逐函数核对返回字段在 UI 侧取用，工作量约等于重写数据层，按方案 §9.1 作为独立推进。
- [ ] P2 补充缺失的 SDK 方法（credentials/capabilities, plugins/catalog）（Req: `requirements.md#req-4`）
  - 决策：延后。需先确认 SDK `admin` namespace 的 credentials/plugins 方法签名是否覆盖 Studio 现有 admin 调用，属 SDK 侧能力核对，非 Studio 单侧可完成。

### Phase 5: 图表与高级功能（2 周）

- [ ] P2 集成图表库（recharts 或 chart.js）（Req: `requirements.md#req-14`）
  - 决策：不引入 recharts/chart.js。轻量可视化用纯 CSS 条形图实现（见第 2 项），避免 +100KB bundle。待真实需要复杂图表（折线/饼图/多系列）且数据源就绪再引入。
- [~] P2 Observability 图表可视化（token/latency 趋势，tool usage 饼图）（Req: `requirements.md#req-14`）
  - 完成：Tools section 新增纯 CSS 水平条形图（tool usage by result_count，top 6，error 高亮红色），无图表库依赖。
  - 决策：token/latency 趋势图延后——当前 Observability 数据是聚合指标（无时序点序列），做趋势图需后端提供时序数据，前端无原始时序。
- [x] P2 数据导出功能（Observability runs CSV/JSON，Evaluation 报告，Audit logs）（Req: `requirements.md#req-14`）
  - 完成：studioUtils 新增 `downloadFile`/`toCsv`/`exportFilename` 工具；Observability runs（CSV+JSON）、Evaluation 报告（CSV+JSON）、Audit events（CSV）均加导出按钮，文件名带时间戳。
- [~] P2 搜索与过滤增强（Debug event 搜索，Observability 时间范围，Audit 时间过滤）（Req: `requirements.md#req-14`）
  - 完成：Debug 页面新增事件搜索框（按 type/title/payload/meta 过滤，匹配空态）；Observability 时间范围（all/hour/day）已存在。
  - 决策：Audit 时间过滤延后——当前 audit events 来自 observability timeline（已受全局 window 过滤），单独的 audit 时间选择器收益有限。
- [~] P2 编辑器增强（Files 页面语法高亮 CodeMirror/Monaco，YAML/JSON schema 校验）（Req: `requirements.md#req-14`）
  - 完成：Files 页面新增轻量实时校验状态行（mcp.json 用 JSON.parse，agent.yaml 检测 Tab 缩进，AGENTS.md 标记 markdown），不阻断保存。
  - 决策：不引入 CodeMirror/Monaco。语法高亮需 Monaco（~2MB）或 CodeMirror 6（~150KB），bundle 代价过大；当前 TextArea + 轻量校验已覆盖格式正确性核心需求。语法高亮待用户明确需求再引入。

## 验收标准

### 视觉验收

- [ ] 所有页面使用统一颜色系统（温暖奶油背景 #F7F4EF，赤陶橙 accent #C4612F）
- [ ] 所有页面遵循紧凑间距规范（page padding 16px, panel padding 10-12px, gap 6-10px）
- [ ] 所有指标使用 stat-strip 或 monospace 数字
- [ ] 所有表格行高 32-36px（从 48px 降低）
- [ ] 所有 panel border-radius 6px, padding 10-12px（从 12px/14-18px 降低）

### 性能验收

- [ ] Observability 首屏显示 8+ 条 run（当前 ~5 条）
- [ ] 页面切换 <300ms（不含 API 调用）
- [ ] 大列表（100+ 行）滚动流畅（60fps）
- [ ] 所有 API 请求带 loading 状态
- [ ] 错误自动重试 1 次，失败后 degraded 状态

### 功能验收

- [ ] 所有页面支持数据刷新（手动 + 自动）
- [ ] SSE 实时流正常工作（Chat 运行中，Debug 回放）
- [ ] 缓存策略正常工作（agent catalog 30s, tool catalog 15s, metrics 10s）
- [ ] 乐观更新正常工作（Credentials CRUD, Config 保存）
- [ ] Toast/Error/Empty 状态正常展示

### 量化目标

- [ ] 首屏信息量提升 60%+（5 条 → 8-10 条）
- [ ] 页面加载时间降低 37%+（800ms → <500ms）
- [ ] 垂直空间利用率提升 62%+（40% → >65%）
- [ ] 组件复用率提升 133%+（30% → >70%）

## 决策 & 争议点

- [ ] 图表库选择：recharts（React 原生，包体积小）vs chart.js（功能强大，生态丰富）
- [ ] 编辑器库选择：CodeMirror 6（轻量）vs Monaco（VS Code 同款，功能全）
- [ ] 是否提供 "Classic View" 切换以缓解用户习惯变化

## 参考

- `docs/architecture/control-plane/studio-pages-inventory.md` — 页面功能清单
- `docs/architecture/control-plane/studio-ui-optimization-plan.md` — 优化设计方案
- `docs/architecture/control-plane/studio-control-plane-and-observability.md` — 控制面与观测面口径
- `docs/architecture/api/sdk-public-surface.md` — SDK public surface
- Grafana Dashboard 设计规范
- Datadog UI 设计系统
- Linear App 紧凑布局
