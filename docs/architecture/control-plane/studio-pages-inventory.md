<!--
---
doc_kind: architecture
status: active
tags: ["studio", "ui", "pages", "inventory"]
summary: AnyAgent Studio 当前页面功能清单、数据源、API 依赖与待优化项
related: ["studio-control-plane-and-observability.md"]
---
-->

# Studio Pages Inventory

本文档记录 AnyAgent Studio 当前所有页面的实际功能、数据源、API 调用和待优化项。

## 1. 页面清单

### 1.1 Use 模式页面（7个）

| 页面 | 文件 | 行数 | 状态 | 主要功能 |
|---|---|---|---|---|
| Home | `HomePage.tsx` | ~400 | ✅ 已实现 | Chat 界面、实时流式输出、最近运行摘要 |
| Agents | `AgentsPage.tsx` | ~300 | ✅ 已实现 | Agent 列表、选择、能力展示 |
| Sessions | `SessionsPage.tsx` | ~250 | ✅ 已实现 | Session 列表、Run 历史、状态检查 |
| Observability | `ObservabilityPage.tsx` | ~500 | ✅ 已实现 | 聚合指标、工具统计、错误列表、Timeline |
| Evaluations | `EvaluationsPage.tsx` | ~400 | ✅ 已实现 | Dataset CRUD、评测运行、结果查询 |
| Prompts | `PromptsPage.tsx` | ~300 | ✅ 已实现 | Prompt 预览、版本快照、Diff、Restore |
| Settings | `SettingsPage.tsx` | ~200 | ✅ 已实现 | 连接配置、默认值管理 |

### 1.2 Build 模式页面（8个）

| 页面 | 文件 | 行数 | 状态 | 主要功能 |
|---|---|---|---|---|
| Home | `HomePage.tsx` | 共用 | ✅ 已实现 | 构建工作台摘要、健康检查 |
| Agents | `AgentsPage.tsx` | 共用 | ✅ 已实现 | Agent 创建、管理、exposed 状态 |
| Configure | `ConfigurePage.tsx` + panels | ~600 | ✅ 已实现 | 连接配置、Agent 创建、Effective Config、Tool Catalog |
| Skills | `SkillsPage.tsx` | ~350 | ✅ 已实现 | Skills 导入、启用、更新、source metadata |
| MCP | `McpPage.tsx` | ~400 | ✅ 已实现 | MCP server drafts、连接测试、mcp.json 编辑 |
| Tools | `ToolsPage.tsx` | ~300 | ✅ 已实现 | Effective/Available tools、catalog 查询 |
| Credentials | `CredentialsPage.tsx` | ~350 | ✅ 已实现 | Credential Vault CRUD、capability matrix |
| Debug | `DebugPage.tsx` | ~400 | ✅ 已实现 | Stage events、raw payload、sandbox diagnostics |
| Audit | `AuditPage.tsx` | ~250 | ✅ 已实现 | 审计事件查询、policy denials |
| Files | `FilesPage.tsx` | ~300 | ✅ 已实现 | AGENTS.md/agent.yaml/mcp.json 编辑器 |
| Settings | `SettingsPage.tsx` | 共用 | ✅ 已实现 | Admin health、storage/credential capabilities |

**总计**: 15 个页面文件，~3660 行代码

## 2. 各页面数据源与 API 依赖

### 2.1 Home 页面

**Use 模式**
- 数据源: 
  - `POST /v1/responses` (OpenAI compatible)
  - `GET /internal/events/stream?response_id=`
  - `GET /internal/agents/{id}`
- 功能:
  - ✅ Chat 输入框 + 实时流式输出
  - ✅ 最近 run 摘要
  - ✅ Agent 能力概览
  - ⚠️ 缺少: 会话历史快速导航

**Build 模式**
- 数据源:
  - `GET /healthz`
  - `GET /admin/storage/health`
  - Agent/Skills/MCP/Tools 状态聚合
- 功能:
  - ✅ 构建健康摘要
  - ✅ 未保存变更提示
  - ⚠️ 缺少: 配置健康评分、构建信号

### 2.2 Agents 页面

**数据源**
- `GET /internal/agents?include_unexposed=true`
- `GET /internal/agents/{id}`
- `GET /admin/workspace/agents` (Build 模式)

**功能**
- ✅ Agent 列表展示
- ✅ Agent 选择与切换
- ✅ 模型/工具/技能能力展示
- ✅ Exposed 状态标记
- ✅ 创建 Agent 入口 (Build 模式)
- ⚠️ 缺少: Agent 复制、批量管理

### 2.3 Sessions 页面

**数据源**
- `GET /internal/sessions`
- `GET /internal/sessions/{key}`
- `GET /internal/observability/runs`
- `GET /v1/responses/{id}`
- `GET /internal/events/list`

**功能**
- ✅ Session 列表
- ✅ 会话级聚合（run count, total tokens, avg latency）
- ✅ Run 列表与状态展示
- ✅ 选择 run 查看详情
- ⚠️ 缺少: Cancel response（需 server 支持）
- ⚠️ 缺少: Session 导出、归档

### 2.4 Observability 页面

**数据源**
- `GET /internal/observability/runs`
- `GET /internal/observability/summary`
- `GET /internal/observability/metrics`
- `GET /internal/observability/tools`
- `GET /internal/observability/errors`
- `GET /internal/observability/timeline`
- `GET /internal/observability/traces/{trace_id}`
- `GET /internal/observability/alerts`

**功能**
- ✅ Agent/Session 级聚合指标
- ✅ Run history drill-down
- ✅ Tool 聚合统计
- ✅ Error 列表与过滤
- ✅ Timeline 查询（支持 trace_id）
- ✅ Token/Latency/Turn 统计
- ⚠️ 缺少: 图表可视化（当前仅数字）
- ⚠️ 缺少: 时间范围选择器
- ⚠️ 缺少: 导出 CSV/JSON

### 2.5 Evaluations 页面

**数据源**
- `GET /internal/evaluations/datasets`
- `POST /internal/evaluations/datasets`
- `POST /internal/evaluations/run`
- `GET /internal/evaluations/runs`
- Observability runs/summary/timeline (用于选择候选 runs)

**功能**
- ✅ Dataset CRUD
- ✅ 从 observability runs 选择候选
- ✅ 按错误/高延迟/高价值筛选
- ✅ 生成 evaluation seed
- ✅ 执行 exact-match v0 评测
- ✅ 查询历史结果
- ⚠️ 缺少: 自定义评测器
- ⚠️ 缺少: 批量评测调度
- ⚠️ 缺少: 评测报告导出

### 2.6 Prompts 页面

**数据源**
- `GET /internal/prompt/bundle`
- `GET /internal/prompt/versions`
- `GET /internal/prompt/versions/{id}`
- `GET /internal/prompt/versions/diff`
- `POST /internal/prompt/versions/{id}/restore` (admin-gated)
- `GET /internal/events/list` (查询 `anyagent.prompt.context`)

**功能**
- ✅ Prompt preview 摘要
- ✅ 选中 skills 展示
- ✅ 工具上下文展示
- ✅ Cache key 展示
- ✅ 版本快照列表
- ✅ 版本 diff
- ✅ Admin-gated restore
- ⚠️ 缺少: Prompt 模板编辑
- ⚠️ 缺少: Prompt 优化建议

### 2.7 Configure 页面 (Build 模式核心)

**数据源**
- `GET /internal/agents/{id}`
- `GET /admin/workspace/agents/{id}/config`
- `GET /admin/workspace/agents/{id}/files`
- Skills/MCP/Tools/Credentials admin APIs

**功能**
- ✅ Connection draft/test/apply
- ✅ Create agent panel
- ✅ Effective config 查看
- ✅ Tool catalog section
- ✅ Source files 快速导航
- ⚠️ 缺少: agent.yaml 常用配置表单
- ⚠️ 缺少: 配置校验与提示

### 2.8 Skills 页面

**数据源**
- `GET /internal/skills/list`
- `POST /admin/workspace/agents/{id}/skills/import` (with channel)
- `POST /admin/workspace/agents/{id}/skills/update`
- `PUT /admin/workspace/agents/{id}/skills/{skill_id}/enabled`

**功能**
- ✅ Skills 列表
- ✅ Channel 选择（skills.sh/github/local_upload/registry）
- ✅ Import/Install
- ✅ Enable/Disable toggle
- ✅ Default-selected 管理
- ✅ Source metadata 展示
- ✅ Update check/apply
- ⚠️ 缺少: Skill 预览与测试

### 2.9 MCP 页面

**数据源**
- `GET /admin/workspace/agents/{id}/mcp/servers`
- `PUT /admin/workspace/agents/{id}/mcp/servers/{label}/enabled`
- `POST /admin/workspace/agents/{id}/mcp/servers/{label}/test`
- `GET /admin/workspace/agents/{id}/files/mcp_json`
- `PUT /admin/workspace/agents/{id}/files/mcp_json`

**功能**
- ✅ MCP server drafts 管理
- ✅ Streamable HTTP/SSE/stdio 配置
- ✅ Enabled/Disabled/Inherited 状态摘要
- ✅ Credential ref 关联
- ✅ 连接测试
- ✅ 保存 mcp.json
- ✅ Invalid JSON recovery
- ⚠️ 缺少: MCP tools 预览
- ⚠️ 缺少: MCP server 日志查看

### 2.10 Tools 页面

**数据源**
- `GET /internal/tools/catalog`
- `GET /admin/tools/catalog`
- `POST /internal/tools/explain`
- Agent config (requested_tool_names)

**功能**
- ✅ Effective tools 列表
- ✅ Available tools 列表
- ✅ Tool kind/reason/toolset version
- ✅ Tool explain (为何可见/不可见)
- ⚠️ 缺少: requested_tool_names toggle UI
- ⚠️ 缺少: Tool 参数预览
- ⚠️ 缺少: Tool 测试执行

### 2.11 Credentials 页面

**数据源**
- `GET /admin/credentials`
- `POST /admin/credentials`
- `DELETE /admin/credentials/{id}`
- `GET /admin/credentials/capabilities`

**功能**
- ✅ Credential refs 列表
- ✅ Create/Delete
- ✅ Scope 管理 (agent/session/workspace)
- ✅ Kind 选择 (bearer_token/api_key/basic_auth)
- ✅ 只写 secret (不回显)
- ✅ Capability matrix 展示
- ⚠️ 缺少: Credential 轮转
- ⚠️ 缺少: Expires_at 管理

### 2.12 Debug 页面

**数据源**
- `GET /internal/events/list`
- `GET /internal/events/stream?response_id=`
- `GET /internal/prompt/bundle`
- `GET /admin/sandboxes`
- `GET /admin/sandboxes/workspaces/{id}/snapshots`
- `POST /admin/sandboxes/workspaces/{id}/reclaim`
- `GET /internal/responses/{response_id}/tool-executions`
- `GET /internal/responses/{response_id}/model-request`
- `GET /internal/responses/{response_id}/prompt-context`

**功能**
- ✅ Stage events 列表
- ✅ Raw event JSON 查看
- ✅ Response id selector
- ✅ Prompt bundle raw view
- ✅ Sandbox workspace 列表
- ✅ Snapshot drill-down
- ✅ 强制回收
- ✅ Tool execution detail replay
- ✅ Model request replay
- ✅ Prompt context replay
- ⚠️ 缺少: Event 搜索与过滤
- ⚠️ 缺少: Event diff 对比

### 2.13 Audit 页面

**数据源**
- `GET /internal/audit/events`
- Observability runs/errors/timeline (audit_ref 关联)

**功能**
- ✅ 审计事件查询
- ✅ 按 credential_id/agent_id/session_key 过滤
- ✅ Policy denials 展示
- ✅ Audit_ref 关联 run records
- ⚠️ 缺少: 时间范围过滤
- ⚠️ 缺少: 审计日志导出

### 2.14 Files 页面

**数据源**
- `GET /admin/workspace/agents/{id}/files`
- `PUT /admin/workspace/agents/{id}/files/{kind}`
- SHA256 optimistic save

**功能**
- ✅ AGENTS.md 编辑器
- ✅ agent.yaml 编辑器
- ✅ mcp.json 编辑器
- ✅ Active/Disabled 状态控制
- ✅ SHA256 optimistic save
- ✅ Reload 功能
- ⚠️ 缺少: 语法高亮
- ⚠️ 缺少: YAML/JSON schema 校验
- ⚠️ 缺少: 文件历史版本

### 2.15 Settings 页面

**Use 模式**
- 功能: 个人连接配置、默认 agent/session/model
- ✅ 已实现

**Build 模式**
- 数据源:
  - `GET /healthz`
  - `GET /admin/storage/health`
  - `GET /admin/credentials/capabilities`
  - Sandbox/Workspace diagnostics
- 功能:
  - ✅ Server connection 配置
  - ✅ Admin key test
  - ✅ Storage health 展示
  - ✅ Credential capability 展示
  - ⚠️ 缺少: Server management diagnostics 细节

## 3. 核心 Hooks 清单

| Hook | 文件 | 职责 | 状态 |
|---|---|---|---|
| useWorkspaceCatalog | `hooks/useWorkspaceCatalog.ts` | Workspace agent/skill catalog | ✅ |
| useAgentFiles | `hooks/useAgentFiles.ts` | Agent pack 源文件加载与编辑 | ✅ |
| useMcpDrafts | `hooks/useMcpDrafts.ts` | MCP drafts 管理与 mcp.json 同步 | ✅ |
| useToolCatalog | `hooks/useToolCatalog.ts` | Tool catalog 查询与状态 | ✅ |
| useCredentials | `hooks/useCredentials.ts` | Credential Vault 管理 | ✅ |
| useSkillsManagement | `hooks/useSkillsManagement.ts` | Skills 导入/启用/更新 | ✅ |
| useObservability | `hooks/useObservability.ts` | Observability 聚合查询 | ✅ |

## 4. 待优化清单

### 4.1 高优先级（P0）

1. **UI 密度优化**（对应 §8 高密度 UI 规范）
   - [ ] 替换独立 metric-card 为 stat-strip
   - [ ] 紧凑间距：global gap 6-10px, panel padding 10-12px
   - [ ] 表格行高从 48px 降至 32-36px
   - [ ] Monospace 数字对齐
   - [ ] 验收首屏信息密度

2. **TypeScript SDK 迁移**（对应 §7 TypeScript SDK 集成策略）
   - [ ] Phase 1: 用 `@anyagent/sdk` 替换 `anyagentClient.ts` 类型
   - [ ] Phase 2: 消费 SDK `client.responses.stream()` SSE
   - [ ] Phase 3: 消费 SDK sessions/observability namespace
   - [ ] 补充缺失的 SDK 方法（credentials/capabilities, plugins/catalog）

3. **实时数据与缓存**（对应 §9 实时数据与缓存模式）
   - [ ] 实现 SSE 连接管理（断线重连、cleanup）
   - [ ] 实现 SWR 缓存策略（staleTime, background refetch, deduplication）
   - [ ] 实现 Debounce（tool catalog 300ms, observability filter 200ms）
   - [ ] 实现错误恢复（重试、degraded 状态）

### 4.2 中优先级（P1）

1. **图表可视化**
   - [ ] Observability 页面添加 token/latency 趋势图
   - [ ] Tool usage 饼图
   - [ ] Error rate 时间线
   - [ ] 建议库: lightweight chart.js / recharts

2. **数据导出**
   - [ ] Observability runs 导出 CSV/JSON
   - [ ] Evaluation 报告导出
   - [ ] Audit logs 导出
   - [ ] Timeline 导出

3. **搜索与过滤增强**
   - [ ] Debug 页面 event 搜索
   - [ ] Observability 时间范围选择器
   - [ ] Audit 页面时间范围过滤
   - [ ] Sessions 页面高级过滤

4. **编辑器增强**
   - [ ] Files 页面语法高亮（CodeMirror / Monaco）
   - [ ] YAML/JSON schema 实时校验
   - [ ] agent.yaml 常用配置表单
   - [ ] 文件历史版本（依赖 server 支持）

### 4.3 低优先级（P2）

1. **批量操作**
   - [ ] Agent 复制与批量管理
   - [ ] Session 批量导出/归档
   - [ ] Evaluation 批量调度

2. **高级功能**
   - [ ] Skill 预览与测试
   - [ ] MCP tools 预览
   - [ ] Tool 参数预览与测试执行
   - [ ] Prompt 优化建议
   - [ ] 自定义评测器

3. **运维增强**
   - [ ] MCP server 日志查看
   - [ ] Credential 轮转管理
   - [ ] Server management diagnostics 细节
   - [ ] Cancel response（需 server 支持）

## 5. 设计系统优化

### 5.1 当前设计问题

1. **信息密度低**
   - metric-card 独立卡片占用过多空间
   - Panel padding 16-24px 过大
   - 表格行高 48px 浪费垂直空间
   - 首屏显示内容过少

2. **视觉层级不清晰**
   - 嵌套过深（Page → Section → Card → Card.Header → Content）
   - 边框与阴影过多
   - 颜色对比度不够

3. **交互响应不足**
   - API 调用无 loading 状态
   - 错误处理不统一
   - 缺少乐观更新

### 5.2 设计优化方向

参考 Grafana/Datadog 高密度仪表盘风格：

1. **扁平化布局**
   - Page → Section → Content（移除冗余 Card 层）
   - 统一 panel 样式（border-radius 6px, padding 8-12px）
   - stat-strip 内联指标

2. **紧凑间距**
   - Global gap: 6-10px
   - Panel padding: 10-12px
   - Row height: 32-36px
   - Section margin: 12px

3. **信息优先**
   - 折叠默认（timeline/error detail/turn breakdown）
   - 表格优先于列表
   - Monospace 数字
   - 首屏信息密度验收

## 6. 技术债务

### 6.1 代码组织

- ✅ 已完成页面级 code splitting
- ✅ 已完成 hooks 拆分
- ✅ 已完成 Configure panels 拆分
- ⚠️ `StudioApp.tsx` 仍然过大（~1500 行），需要进一步拆分全局状态管理

### 6.2 类型安全

- ⚠️ `anyagentClient.ts` 手写类型与 protocol 可能不同步
- ⚠️ 缺少运行时类型校验（建议迁移到 SDK）
- ⚠️ 部分组件 props 使用 `any`

### 6.3 性能优化

- ⚠️ Observability 页面大数据量渲染性能
- ⚠️ 缺少虚拟滚动（runs/events 列表）
- ⚠️ 缺少请求取消（快速切换时）

### 6.4 测试覆盖

- ❌ 无单元测试
- ❌ 无集成测试
- ❌ 无 E2E 测试

## 7. 下一步行动

### 短期（1-2 周）

1. **UI 密度优化** - 按 §8 规范重构所有页面
2. **TypeScript SDK 迁移** - Phase 1 类型替换
3. **实时数据** - 实现 SSE 与 SWR 缓存

### 中期（1 月）

1. **图表可视化** - Observability 页面添加图表
2. **编辑器增强** - 语法高亮与 schema 校验
3. **数据导出** - CSV/JSON 导出功能

### 长期（2-3 月）

1. **批量操作** - Agent/Session/Evaluation 批量管理
2. **高级功能** - Skill/MCP/Tool 测试预览
3. **测试覆盖** - 补充单元测试与 E2E 测试

## 8. 相关文档

- [studio-control-plane-and-observability.md](./studio-control-plane-and-observability.md) - Studio 控制面与观测面口径
- [sdk-public-surface.md](../api/sdk-public-surface.md) - AnyAgent SDK public surface
- [sdk-compatibility-matrix.md](../api/sdk-compatibility-matrix.md) - SDK 兼容性矩阵
