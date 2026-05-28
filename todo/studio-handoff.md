# Studio 模块研发交接简报

## 你负责什么

`packages/anyagent/studio/` 目录下的所有前端代码。这是 AnyAgent 的可视化管理控制台，一个 SPA，消费后端 typed API。

任务清单：`todo/studio.md`（Phase S1–S8，共 36 个条目，当前已全部完成）

## 当前状态（2026-05-28）

- `todo/studio.md`：36/36 完成，Phase S1–S8 已落地
- 新增前端依赖：`react-router-dom`、`zustand`、`react-markdown`
- 新增本地持久化 store：chat、settings、agent config、UI/theme、toast、evaluation、config snapshots
- 已完成验证：
  - `rtk npm run build`（`packages/anyagent/studio`）
  - `rtk python3 scripts/docs/check.py --root .`
  - `rtk python3 scripts/anyagent_progress.py --root .` 显示 `todo/studio.md [all]: 36/36`
- 本地 dev server 可通过 `http://127.0.0.1:5177/studio/` 返回 Vite HTML。当前环境未安装 Playwright package，且本轮未暴露 in-app Browser callable tool，因此浏览器级点击烟测未完整执行。

## 技术栈（已选定，不要更换）

- React 19 + Vite 8
- HeroUI（组件库）
- Lucide Icons
- OpenAI SDK（browser 模式，用于 chat streaming）
- TypeScript strict

## 核心约束

1. **Studio 只消费 typed API**，不读取 server 内部 Python 模块
   - OpenAI Responses API：`/v1/responses`
   - Internal API：`/internal/*`
   - Admin API：`/admin/*`
   - API 类型定义在 `src/anyagentClient.ts`

2. **不改后端**。如果功能需要新 API，提 issue 描述需求，不要自己加 endpoint

3. **UI 组件优先 HeroUI**，只在确实不够时引入额外库（需说明理由）

4. **性能预算**：首屏 LCP < 2s，交互 INP < 100ms

## 已执行顺序

已按 Phase S1 优先的顺序推进；S8 在末尾统一收口响应式与可访问性。

```
S1 (架构治理) ──→ S2 (Chat) ──→ S5 (Eval/Playground)
       │
       ├──→ S3 (表单/反馈) ──→ S4 (Onboarding)
       │
       ├──→ S6 (搜索/过滤)
       │
       └──→ S7 (版本管理)

S8 (响应式/a11y) 可随时并行
```

## Phase S1 技术方案（已落地）

| 条目 | 方案 |
|------|------|
| 状态管理 | 新增 Zustand，按域拆分 store，放 `src/stores/` |
| 路由 | 新增 react-router v7，使用 hash mode，每个 StudioTab 对应一个 route |
| 错误边界 | 每个 page 组件包裹 React ErrorBoundary |

验收标准：
- StudioApp.tsx 的 useState 数量 < 10
- ConfigurePage 接收 props 数量 < 15
- 所有页面可通过 URL 直达
- 浏览器前进/后退正常
- `npm run build` 零 TS 错误

## 后续开发流程

1. 从 `main` 切分支，命名 `studio/<phase>-<简述>`（如 `studio/s1-state-refactor`）
2. 每个 Phase 完成后提 PR，PR 描述里标注完成了 `todo/studio.md` 哪些条目
3. 合并后在 `todo/studio.md` 里把对应条目打勾 `[x]`

## 如何本地开发

```bash
cd packages/anyagent/studio
npm install
npm run dev          # 启动 dev server，默认 127.0.0.1:5177
npm run build        # 验证 TS + 构建
```

后端（需要单独启动来测试 API 连接）：
```bash
cd packages/anyagent
anyagent serve --workspace <your-workspace-path>
```

## 你不需要关心的

- Python server 代码（`packages/anyagent/src/`）
- Protocol / SDK / Tool Runtime / Storage 等模块
- `todo/` 下其他文件
- `docs/architecture/` 下的后端架构文档

## 参考文档

- Studio 设计约束：`docs/architecture/overview/roadmap.md` § 3.4
- Studio 控制面设计：`docs/architecture/control-plane/studio-control-plane-and-observability.md`
- 当前 API 类型定义：`packages/anyagent/studio/src/anyagentClient.ts`

## 沟通协议

- 遇到需要新 API 的场景 → 提 issue，标 `studio-api-request`
- 遇到 HeroUI 不满足的 UI 需求 → 先找我确认是否引入新库
- Phase 完成 → PR + 在 todo/studio.md 打勾
