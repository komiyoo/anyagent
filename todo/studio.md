# TODO — Studio

Studio 是 AnyAgent 的可视化管理控制台，消费 typed API（OpenAI Responses API、`/internal/*`、`/admin/*`）。
本文件维护 Studio 自身的产品设计与工程任务。

技术栈：React 19 + Vite 8 + HeroUI + Lucide Icons + OpenAI SDK（browser）

---

## Phase S1 — 架构治理（阻塞后续所有功能迭代）

- [x] P0 状态管理重构：将 StudioApp.tsx 40+ useState 拆分为领域 store（Req: studio 可维护性；Module: `studio`；Impl: `packages/anyagent/studio/src/stores/settingsStore.ts:37`、`packages/anyagent/studio/src/stores/chatStore.ts:27`、`packages/anyagent/studio/src/stores/agentConfigStore.ts:34`、`packages/anyagent/studio/src/StudioApp.tsx:82`、`packages/anyagent/studio/src/pages/ConfigurePage.tsx:143`）
  - 候选方案：Zustand（轻量、无 provider boilerplate）
  - 拆分域：connection、agent、chat、observability、skills、mcp、tools、credentials、files
  - 目标：ConfigurePage props 从 130+ 降到 <15
- [x] P0 引入客户端路由：hash router 或 react-router，支持 URL 直达、浏览器前进/后退、链接分享（Req: studio UX 基线；Module: `studio`；Impl: `packages/anyagent/studio/src/main.tsx:9`、`packages/anyagent/studio/src/navigation.tsx:120`、`packages/anyagent/studio/src/StudioApp.tsx:83`）
- [x] P1 代码分割优化：当前 lazy() 已就位，补充 route-level prefetch 与 loading skeleton（Req: studio 性能；Module: `studio`；Impl: `packages/anyagent/studio/src/pages/lazyPages.ts:7`、`packages/anyagent/studio/src/components/PageSkeleton.tsx:5`、`packages/anyagent/studio/src/StudioApp.tsx:93`、`packages/anyagent/studio/src/StudioApp.tsx:620`）
- [x] P1 统一错误边界：为每个 page 包裹 ErrorBoundary，避免单页崩溃导致全局白屏（Req: studio 稳定性；Module: `studio`；Impl: `packages/anyagent/studio/src/components/PageErrorBoundary.tsx:12`、`packages/anyagent/studio/src/StudioApp.tsx:594`）

---

## Phase S2 — Chat 体验完善

- [x] P0 Markdown 渲染：assistant 消息支持 Markdown + 代码高亮（候选 react-markdown + shiki）（Req: studio chat UX；Module: `studio`；Impl: `packages/anyagent/studio/src/components/MarkdownMessage.tsx:49`、`packages/anyagent/studio/src/pages/HomePage.tsx:307`）
- [x] P0 对话持久化：将 messages 写入 localStorage 或 IndexedDB，刷新不丢失（Req: studio chat UX；Module: `studio`；Impl: `packages/anyagent/studio/src/stores/chatStore.ts:11`、`packages/anyagent/studio/src/stores/chatStore.ts:45`、`packages/anyagent/studio/src/stores/chatStore.ts:103`）
- [x] P1 清空对话：添加 "New conversation" 按钮重置 messages（Req: studio chat UX；Module: `studio`；Impl: `packages/anyagent/studio/src/stores/chatStore.ts:129`、`packages/anyagent/studio/src/pages/HomePage.tsx:238`）
- [x] P1 消息操作：复制按钮、重新生成、编辑用户消息重发（Req: studio chat UX；Module: `studio`；Impl: `packages/anyagent/studio/src/pages/HomePage.tsx:83`、`packages/anyagent/studio/src/pages/HomePage.tsx:268`、`packages/anyagent/studio/src/pages/HomePage.tsx:271`、`packages/anyagent/studio/src/pages/HomePage.tsx:276`、`packages/anyagent/studio/src/StudioApp.tsx:413`、`packages/anyagent/studio/src/StudioApp.tsx:430`）
- [x] P2 Streaming 视觉指示：打字光标动画替代静态 "..."（Req: studio chat UX；Module: `studio`；Impl: `packages/anyagent/studio/src/pages/HomePage.tsx:308`、`packages/anyagent/studio/src/styles.css:853`）
- [x] P2 多轮对话管理：对话列表、切换、重命名（Req: studio chat UX；Module: `studio`；Impl: `packages/anyagent/studio/src/stores/chatStore.ts:4`、`packages/anyagent/studio/src/stores/chatStore.ts:144`、`packages/anyagent/studio/src/stores/chatStore.ts:153`、`packages/anyagent/studio/src/pages/HomePage.tsx:248`）

---

## Phase S3 — 表单与反馈体系

- [x] P0 Toast 通知系统：操作成功/失败用 toast 而非内嵌文字状态（Req: studio UX 反馈；Module: `studio`；Impl: `packages/anyagent/studio/src/stores/toastStore.ts:17`、`packages/anyagent/studio/src/components/ToastViewport.tsx:4`、`packages/anyagent/studio/src/StudioApp.tsx:341`）
- [x] P0 表单验证：Create Agent、Settings 等表单添加必填/格式校验与 inline error（Req: studio 数据完整性；Module: `studio`；Impl: `packages/anyagent/studio/src/pages/configure/CreateAgentPanel.tsx:26`、`packages/anyagent/studio/src/pages/SettingsPage.tsx:49`、`packages/anyagent/studio/src/pages/CredentialsPage.tsx:37`）
- [x] P1 确认对话框：危险操作（删除 credential、重置 settings）前弹确认（Req: studio 安全操作；Module: `studio`；Impl: `packages/anyagent/studio/src/StudioApp.tsx:372`、`packages/anyagent/studio/src/StudioApp.tsx:829`）
- [x] P1 表单 label 可见化：Settings 页 Input 补充视觉 label，当前仅有 aria-label（Req: studio 无障碍；Module: `studio`；Impl: `packages/anyagent/studio/src/pages/SettingsPage.tsx:99`、`packages/anyagent/studio/src/pages/configure/CreateAgentPanel.tsx:41`、`packages/anyagent/studio/src/pages/CredentialsPage.tsx:61`）
- [x] P2 操作 loading 状态：按钮 loading spinner + disable 防重复提交（Req: studio UX 反馈；Module: `studio`；Impl: `packages/anyagent/studio/src/pages/SettingsPage.tsx:63`、`packages/anyagent/studio/src/pages/configure/CreateAgentPanel.tsx:60`、`packages/anyagent/studio/src/pages/CredentialsPage.tsx:52`、`packages/anyagent/studio/src/styles.css:423`）

---

## Phase S4 — 空状态与 Onboarding

- [x] P1 首次访问引导：未连接服务时显示 setup wizard（配置 server URL → test → 选择 agent）（Req: studio 新手体验；Module: `studio`；Impl: `packages/anyagent/studio/src/pages/HomePage.tsx:202`）
- [x] P1 空状态升级：各页面空状态添加图示 + 引导 CTA（Req: studio 空状态引导；Module: `studio`；Impl: `packages/anyagent/studio/src/pages/SessionsPage.tsx:65`、`packages/anyagent/studio/src/pages/ObservabilityPage.tsx:201`、`packages/anyagent/studio/src/pages/EvaluationsPage.tsx:64`、`packages/anyagent/studio/src/pages/configure/ToolCatalogSection.tsx:44`）
  - Sessions: "Run your first session" → 跳转 Home
  - Observability: "No telemetry yet" → 引导发起请求
  - Evaluations: "No runs to evaluate" → 引导 Sessions
  - Tools: "No tools loaded" → 加载按钮 prominent
- [x] P2 Quickstart 模板：Home 页 quickstart pill 连接到实际交互式指南（Req: studio 新手体验；Module: `studio`；Impl: `packages/anyagent/studio/src/StudioApp.tsx:695`）

---

## Phase S5 — Evaluations & Playground

- [x] P1 Evaluation 数据集管理：创建/编辑/导入评估数据集（input + expected output）（Req: studio eval 功能；Module: `studio`；Impl: `packages/anyagent/studio/src/stores/evalStore.ts:85`、`packages/anyagent/studio/src/stores/evalStore.ts:153`、`packages/anyagent/studio/src/stores/evalStore.ts:164`、`packages/anyagent/studio/src/pages/EvaluationsPage.tsx:253`、`packages/anyagent/studio/src/pages/EvaluationsPage.tsx:313`）
- [x] P1 评估执行：对选定 runs 自动对比 expected vs actual，生成 pass/fail 报告（Req: studio eval 功能；Module: `studio`；Impl: `packages/anyagent/studio/src/pages/EvaluationsPage.tsx:19`、`packages/anyagent/studio/src/pages/EvaluationsPage.tsx:41`、`packages/anyagent/studio/src/pages/EvaluationsPage.tsx:117`、`packages/anyagent/studio/src/pages/EvaluationsPage.tsx:372`）
- [x] P2 Playground 对比面板：同一 prompt 对比不同 agent 配置的输出（Req: studio playground；Module: `studio`；Impl: `packages/anyagent/studio/src/pages/EvaluationsPage.tsx:126`、`packages/anyagent/studio/src/pages/EvaluationsPage.tsx:168`、`packages/anyagent/studio/src/pages/EvaluationsPage.tsx:455`）
- [x] P2 Prompt 变体测试：批量测试同一 agent 在不同 prompt 下的表现（Req: studio playground；Module: `studio`；Impl: `packages/anyagent/studio/src/stores/evalStore.ts:127`、`packages/anyagent/studio/src/pages/EvaluationsPage.tsx:183`、`packages/anyagent/studio/src/pages/EvaluationsPage.tsx:489`）
- [x] P3 评估结果可视化：pass rate 趋势图、回归检测高亮（Req: studio eval 可视化；Module: `studio`；Impl: `packages/anyagent/studio/src/pages/EvaluationsPage.tsx:424`、`packages/anyagent/studio/src/pages/EvaluationsPage.tsx:431`、`packages/anyagent/studio/src/styles.css:1420`、`packages/anyagent/studio/src/styles.css:1443`）

---

## Phase S6 — 搜索与过滤增强

- [x] P1 Agent 列表搜索：agents 数量多时支持 filter by name（Req: studio 查找效率；Module: `studio`；Impl: `packages/anyagent/studio/src/pages/AgentsPage.tsx:51`、`packages/anyagent/studio/src/pages/AgentsPage.tsx:73`）
- [x] P1 Tool 搜索与分类：按 kind 分组 + 全文搜索（Req: studio 查找效率；Module: `studio`；Impl: `packages/anyagent/studio/src/pages/configure/ToolCatalogSection.tsx:19`、`packages/anyagent/studio/src/pages/configure/ToolCatalogSection.tsx:45`、`packages/anyagent/studio/src/pages/configure/ToolCatalogSection.tsx:66`、`packages/anyagent/studio/src/pages/configure/ToolCatalogSection.tsx:88`）
- [x] P2 Skills 搜索/标签过滤（Req: studio 查找效率；Module: `studio`；Impl: `packages/anyagent/studio/src/pages/SkillsPage.tsx:68`、`packages/anyagent/studio/src/pages/SkillsPage.tsx:139`、`packages/anyagent/studio/src/pages/SkillsPage.tsx:150`）
- [x] P2 Observability timeline 高级过滤：时间范围选择器、multi-select source/status（Req: studio observability UX；Module: `studio`；Impl: `packages/anyagent/studio/src/hooks/useObservability.ts:150`、`packages/anyagent/studio/src/pages/ObservabilityPage.tsx:167`、`packages/anyagent/studio/src/pages/ObservabilityPage.tsx:247`）
- [x] P2 全局搜索（Cmd+K）：跨页面搜索 agents、tools、skills、credentials（Req: studio 导航效率；Module: `studio`；Impl: `packages/anyagent/studio/src/StudioApp.tsx:342`、`packages/anyagent/studio/src/StudioApp.tsx:371`、`packages/anyagent/studio/src/StudioApp.tsx:632`）

---

## Phase S7 — 版本管理与协作

- [x] P2 Agent 配置 diff：展示当前配置与上次保存/服务端的差异（Req: studio 配置可追溯；Module: `studio`；Impl: `packages/anyagent/studio/src/pages/ConfigurePage.tsx:274`、`packages/anyagent/studio/src/pages/ConfigurePage.tsx:302`、`packages/anyagent/studio/src/pages/ConfigurePage.tsx:430`）
- [x] P2 配置快照/回滚：保存配置版本，支持一键回滚（Req: studio 配置安全；Module: `studio`；Impl: `packages/anyagent/studio/src/stores/configVersionStore.ts:32`、`packages/anyagent/studio/src/pages/ConfigurePage.tsx:319`、`packages/anyagent/studio/src/pages/ConfigurePage.tsx:420`、`packages/anyagent/studio/src/pages/ConfigurePage.tsx:465`）
- [x] P3 多 agent 对比视图：并排查看两个 agent 的配置差异（Req: studio 多 agent 管理；Module: `studio`；Impl: `packages/anyagent/studio/src/pages/ConfigurePage.tsx:308`、`packages/anyagent/studio/src/pages/ConfigurePage.tsx:482`、`packages/anyagent/studio/src/pages/ConfigurePage.tsx:506`）
- [x] P3 审计日志独立页面：从 Observability 拆出 audit trail 专页（Req: studio audit UX；Module: `studio`；Impl: `packages/anyagent/studio/src/navigation.tsx:93`、`packages/anyagent/studio/src/pages/lazyPages.ts:14`、`packages/anyagent/studio/src/pages/AuditPage.tsx:14`、`packages/anyagent/studio/src/StudioApp.tsx:811`）

---

## Phase S8 — 响应式与可访问性

- [x] P2 响应式布局：tablet/mobile 断点适配，sidebar 自动折叠（Req: studio 多端；Module: `studio`；Impl: `packages/anyagent/studio/src/StudioApp.tsx:265`、`packages/anyagent/studio/src/styles.css:2339`、`packages/anyagent/studio/src/styles.css:2371`）
- [x] P2 键盘导航：sidebar 支持 arrow key 导航，Tab focus 管理（Req: studio 无障碍；Module: `studio`；Impl: `packages/anyagent/studio/src/StudioApp.tsx:396`、`packages/anyagent/studio/src/StudioApp.tsx:733`、`packages/anyagent/studio/src/styles.css:1815`）
- [x] P2 Dark/Light 主题切换（Req: studio 视觉偏好；Module: `studio`；Impl: `packages/anyagent/studio/src/stores/uiStore.ts:13`、`packages/anyagent/studio/src/StudioApp.tsx:101`、`packages/anyagent/studio/src/StudioApp.tsx:655`、`packages/anyagent/studio/src/StudioApp.tsx:774`、`packages/anyagent/studio/src/styles.css:1722`）
- [x] P3 屏幕阅读器优化：ARIA landmarks、live regions for status（Req: studio 无障碍；Module: `studio`；Impl: `packages/anyagent/studio/src/StudioApp.tsx:694`、`packages/anyagent/studio/src/StudioApp.tsx:771`、`packages/anyagent/studio/src/StudioApp.tsx:785`、`packages/anyagent/studio/src/components/ToastViewport.tsx:7`）

---

## 依赖关系

```
S1 (架构治理) ──→ S2 (Chat) ──→ S5 (Eval/Playground)
       │
       ├──→ S3 (表单/反馈) ──→ S4 (Onboarding)
       │
       ├──→ S6 (搜索/过滤)
       │
       └──→ S7 (版本管理)

S8 (响应式/a11y) 可并行，不阻塞其他 Phase
```

---

## 约定

- Studio 只消费 typed API，不引入 server 内部依赖。
- 新增页面/功能必须支持 URL 路由直达（S1 路由完成后）。
- UI 组件优先使用 HeroUI，只在确实不够时引入额外库。
- 性能预算：首屏 < 2s（LCP），交互 < 100ms（INP）。
