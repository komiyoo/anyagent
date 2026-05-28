# TODO — Studio

Studio 是 AnyAgent 的可视化管理控制台，消费 typed API（OpenAI Responses API、`/internal/*`、`/admin/*`）。
本文件维护 Studio 自身的产品设计与工程任务。

技术栈：React 19 + Vite 8 + HeroUI + Lucide Icons + OpenAI SDK（browser）

---

## Phase S1 — 架构治理（阻塞后续所有功能迭代）

- [ ] P0 状态管理重构：将 StudioApp.tsx 40+ useState 拆分为领域 store（Req: studio 可维护性）
  - 候选方案：Zustand（轻量、无 provider boilerplate）
  - 拆分域：connection、agent、chat、observability、skills、mcp、tools、credentials、files
  - 目标：ConfigurePage props 从 130+ 降到 <15
- [ ] P0 引入客户端路由：hash router 或 react-router，支持 URL 直达、浏览器前进/后退、链接分享（Req: studio UX 基线）
- [ ] P1 代码分割优化：当前 lazy() 已就位，补充 route-level prefetch 与 loading skeleton（Req: studio 性能）
- [ ] P1 统一错误边界：为每个 page 包裹 ErrorBoundary，避免单页崩溃导致全局白屏（Req: studio 稳定性）

---

## Phase S2 — Chat 体验完善

- [ ] P0 Markdown 渲染：assistant 消息支持 Markdown + 代码高亮（候选 react-markdown + shiki）（Req: studio chat UX）
- [ ] P0 对话持久化：将 messages 写入 localStorage 或 IndexedDB，刷新不丢失（Req: studio chat UX）
- [ ] P1 清空对话：添加 "New conversation" 按钮重置 messages（Req: studio chat UX）
- [ ] P1 消息操作：复制按钮、重新生成、编辑用户消息重发（Req: studio chat UX）
- [ ] P2 Streaming 视觉指示：打字光标动画替代静态 "..."（Req: studio chat UX）
- [ ] P2 多轮对话管理：对话列表、切换、重命名（Req: studio chat UX）

---

## Phase S3 — 表单与反馈体系

- [ ] P0 Toast 通知系统：操作成功/失败用 toast 而非内嵌文字状态（Req: studio UX 反馈）
- [ ] P0 表单验证：Create Agent、Settings 等表单添加必填/格式校验与 inline error（Req: studio 数据完整性）
- [ ] P1 确认对话框：危险操作（删除 credential、重置 settings）前弹确认（Req: studio 安全操作）
- [ ] P1 表单 label 可见化：Settings 页 Input 补充视觉 label，当前仅有 aria-label（Req: studio 无障碍）
- [ ] P2 操作 loading 状态：按钮 loading spinner + disable 防重复提交（Req: studio UX 反馈）

---

## Phase S4 — 空状态与 Onboarding

- [ ] P1 首次访问引导：未连接服务时显示 setup wizard（配置 server URL → test → 选择 agent）（Req: studio 新手体验）
- [ ] P1 空状态升级：各页面空状态添加图示 + 引导 CTA（Req: studio 空状态引导）
  - Sessions: "Run your first session" → 跳转 Home
  - Observability: "No telemetry yet" → 引导发起请求
  - Evaluations: "No runs to evaluate" → 引导 Sessions
  - Tools: "No tools loaded" → 加载按钮 prominent
- [ ] P2 Quickstart 模板：Home 页 quickstart pill 连接到实际交互式指南（Req: studio 新手体验）

---

## Phase S5 — Evaluations & Playground

- [ ] P1 Evaluation 数据集管理：创建/编辑/导入评估数据集（input + expected output）（Req: studio eval 功能）
- [ ] P1 评估执行：对选定 runs 自动对比 expected vs actual，生成 pass/fail 报告（Req: studio eval 功能）
- [ ] P2 Playground 对比面板：同一 prompt 对比不同 agent 配置的输出（Req: studio playground）
- [ ] P2 Prompt 变体测试：批量测试同一 agent 在不同 prompt 下的表现（Req: studio playground）
- [ ] P3 评估结果可视化：pass rate 趋势图、回归检测高亮（Req: studio eval 可视化）

---

## Phase S6 — 搜索与过滤增强

- [ ] P1 Agent 列表搜索：agents 数量多时支持 filter by name（Req: studio 查找效率）
- [ ] P1 Tool 搜索与分类：按 kind 分组 + 全文搜索（Req: studio 查找效率）
- [ ] P2 Skills 搜索/标签过滤（Req: studio 查找效率）
- [ ] P2 Observability timeline 高级过滤：时间范围选择器、multi-select source/status（Req: studio observability UX）
- [ ] P2 全局搜索（Cmd+K）：跨页面搜索 agents、tools、skills、credentials（Req: studio 导航效率）

---

## Phase S7 — 版本管理与协作

- [ ] P2 Agent 配置 diff：展示当前配置与上次保存/服务端的差异（Req: studio 配置可追溯）
- [ ] P2 配置快照/回滚：保存配置版本，支持一键回滚（Req: studio 配置安全）
- [ ] P3 多 agent 对比视图：并排查看两个 agent 的配置差异（Req: studio 多 agent 管理）
- [ ] P3 审计日志独立页面：从 Observability 拆出 audit trail 专页（Req: studio audit UX）

---

## Phase S8 — 响应式与可访问性

- [ ] P2 响应式布局：tablet/mobile 断点适配，sidebar 自动折叠（Req: studio 多端）
- [ ] P2 键盘导航：sidebar 支持 arrow key 导航，Tab focus 管理（Req: studio 无障碍）
- [ ] P2 Dark/Light 主题切换（Req: studio 视觉偏好）
- [ ] P3 屏幕阅读器优化：ARIA landmarks、live regions for status（Req: studio 无障碍）

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
