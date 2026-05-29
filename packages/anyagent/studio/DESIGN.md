# Design System: AnyAgent Studio

## 1. Visual Theme & Atmosphere

A precision-tool interface for AI agent orchestration — **Cockpit Dense (Density 7)** with
**Offset Asymmetric (Variance 6)** layouts and **Fluid CSS (Motion 6)** micro-interactions.
The atmosphere is clinical yet warm — like a well-lit architecture studio where every surface
serves a purpose. Dark mode is the primary canvas; light mode is a deliberate inversion for
bright environments.

- **Density:** Daily App Balanced → Cockpit Dense (6–7). Information-rich panels with
  generous internal breathing room. No wasted whitespace; every pixel earns its place.
- **Variance:** Offset Asymmetric (6). Hero sections use split layouts. Sidebar is the
  only strictly symmetric element — workspace content breaks free from centered patterns.
- **Motion:** Fluid CSS (6). Spring-physics on interactive surfaces. Staggered list reveals.
  Perpetual micro-loops on live indicators (pulse, shimmer). Hardware-accelerated transforms only.

## 2. Color Palette & Roles

### Light Mode

- **Canvas Base** (#F8FAFC) — Page background, negative space
- **Pure Surface** (#FFFFFF) — Cards, panels, input backgrounds
- **Deep Slate Ink** (#0F172A) — Primary text, highest contrast
- **Muted Steel** (#64748B) — Secondary text, metadata, descriptions
- **Quiet Border** (#E2E8F0) — Structural dividers, 1px separators
- **Frost Overlay** (#F1F5F9) — Row hover states, subtle grouping backgrounds
- **Signal Blue** (#2563EB) — Single accent: CTAs, active states, focus rings, selected items. Saturation 78%.

### Dark Mode (Primary Canvas)

- **Canvas Base** (#0B1120) — Deep midnight page background
- **Raised Surface** (#1A2332) — Cards, panels, elevated containers
- **High Contrast Ink** (#F1F5F9) — Primary text on dark
- **Steel Mist** (#94A3B8) — Secondary text on dark
- **Night Border** (#1E293B) — Dark structural lines
- **Frost Overlay Dark** (#1E2A3D) — Row hover, group separation
- **Signal Blue Dark** (#3B82F6) — Accent on dark surfaces, slightly brighter for contrast

### Functional Tokens

- **Success** (#10B981 / #34D399 dark) — Passed, connected, healthy
- **Warning** (#F59E0B / #FBBF24 dark) — Pending, degraded, needs attention
- **Error** (#EF4444 / #F87171 dark) — Failed, denied, disconnected
- **Info** (#2563EB / #3B82F6 dark) — Neutral informational states

### Banned
- Pure black (#000000)
- Purple/neon glows
- Oversaturated accents (saturation must stay below 80%)
- Warm/cool gray fluctuation — stick to Slate family throughout

## 3. Typography Rules

- **Display/Headlines:** `Geist` — Weight 700, tracking -0.02em. Hierarchy through weight
  and color contrast, not massive size jumps.
- **Body/UI:** `Geist` — Weight 400–500, line-height 1.55. Max 65 characters per line
  in prose contexts (chat messages, descriptions).
- **Mono:** `Geist Mono` — All numbers in metric cards, code blocks, timestamps, hashes.
  Weight 400 for body, 500 for emphasis.
- **Dashboard Constraint:** Sans-serif pairings only. `Geist` + `Geist Mono` is the
  exclusive pairing for this dashboard interface.

### Type Scale (clamp-based for responsive headlines)

| Token | Size | Usage |
|-------|------|-------|
| `text-2xs` | 10px | Nav group labels, keybinds, tiny badges |
| `text-xs` | 11px | Metric labels, secondary metadata, status chips |
| `text-sm` | 12px | Body rows, nav items, button text, form labels |
| `text-base` | 14px | Panel titles, section headings, card emphasis |
| `text-lg` | 16px | Page title, primary headlines |
| `text-xl` | 20px | Metric values in cards |
| `text-2xl` | 24px | Hero values, large stat displays |

### Banned
- Inter font (replaced with Geist)
- Generic serif fonts (Times New Roman, Georgia, Garamond, Palatino)
- Gradient text on headings
- System font stack fallbacks in CSS — force Geist loading

## 4. Component Stylings

### Buttons
- **Shape:** Rounded corners (6px for small, 8px for standard). Flat fill — no glassmorphism,
  no neumorphism, no outer glows.
- **Primary:** Signal Blue fill, white text. Active state: translateY(1px) tactile press,
  brightness(0.92). Focus ring: 2px Signal Blue outline with 2px offset.
- **Secondary/Ghost:** Transparent fill, Slate Ink text, Quiet Border stroke. Hover:
  Frost Overlay background.
- **Icon-only:** 28x28px (touch-friendly 44px on mobile). Same border styling as ghost.
- **Disabled:** 50% opacity, no hover/active states, cursor default.
- **Danger variant:** Error color for destructive actions (delete, remove, revoke).

### Cards / Panels
- **Shape:** Border radius 10px. 1px Quiet Border stroke. No box-shadow in light mode;
  subtle shadow (0 1px 3px rgba(0,0,0,0.3)) in dark mode for depth perception.
- **Header:** 40px min-height, border-bottom separator, title left-aligned, actions right-aligned.
- **Content:** 14px padding internal, no overflow hidden (let children define scroll).
- **Usage Constraint:** In dense layouts (Observability, Configure), replace card containers
  with border-top dividers and negative space grouping.

### Inputs / Forms
- **Layout:** Label above input (control-label pattern). Helper text optional below label.
  Error text below input in Error color.
- **Style:** Height 36-38px for single-line inputs. 1px Quiet Border, 6px radius.
  Focus: 2px Signal Blue ring (not border color change — ring prevents layout shift).
- **TextArea:** Same border style, min-height 60px for composer, 430px for code editors.
  Monospace font for code/text editors.
- **No floating labels** — they reduce scannability and cause accessibility issues.

### Loaders / Skeletons
- **Skeletal Shimmer:** Match exact layout dimensions of loaded content. Animated gradient
  sweep (110deg, transparent → rgba(255,255,255,0.7) → transparent). Duration 1.25s.
- **Button Spinner:** 14x14px border-2 circle, currentColor with transparent right edge,
  linear infinite spin 0.75s.
- **No circular spinners** for page/panel loading — always use skeleton placeholders.

### Empty States
- Composed compositions with icon, heading, description, and CTA.
- Icon in a rounded-full container with accent-tinted background.
- No "No data" text without guidance on how to populate.

### Toast Notifications
- Fixed bottom-right, 360px max-width, auto-dismiss after 4s.
- 4px left border color-coded: Success green, Error red, Info blue.
- Shadow: 0 16px 40px rgba(15, 23, 42, 0.16).

## 5. Layout Principles

### Shell Architecture
- **Grid:** `grid-template-columns: 242px minmax(0, 1fr)` (collapsible to 68px).
- **Sidebar:** Sticky top-0, full viewport height, independent scroll overflow.
  Navigation items with 16px icon + label + optional count badge or shortcut.
- **Workspace Header:** 40px height, brand icon, agent name + status, quick-access pills,
  theme toggle. Border-bottom separation.
- **Page Shell:** `padding: 0 20px 20px`. Page title bar with icon + title + subtitle.

### Grid Systems
- **Main Grid:** `minmax(0, 1.1fr) minmax(340px, 0.9fr)` — asymmetric two-column.
- **Metric Grid:** `repeat(4, minmax(0, 1fr))` — 4-column on desktop, 2 on tablet, 1 on mobile.
- **Configure Grid:** `minmax(0, 1.35fr) minmax(340px, 0.65fr)` — wider editor column.
- **Agent Directory:** `repeat(auto-fit, minmax(240px, 1fr))` — flexible card grid.

### Banned Layouts
- 3-column equal card rows — replace with 2-column zig-zag or asymmetric grid.
- Centered Hero sections — force Split Screen, Left-Aligned, or Asymmetric Whitespace.
- Horizontal scroll on mobile — all multi-column layouts collapse to single column.
- Overlapping elements — every element occupies its own clean spatial zone.
- `calc()` percentage hacks — use CSS Grid fractions exclusively.

### Responsive Strategy
- **>= 1180px:** Full multi-column layouts.
- **768px-1180px:** Single-column shell, sidebar becomes horizontal nav.
- **< 768px:** All columns collapse to single. Sidebar sticky with max-height 52vh.
- **< 640px:** Reduced padding (14px), wrapped header, composer single-column.
- **Typography:** Headlines scale via clamp(). Body minimum 14px.
- **Touch:** All interactive elements minimum 44px tap target.

## 6. Motion & Interaction

### Spring Physics (Default)
```
stiffness: 100, damping: 20, mass: 1
```
Applied to: panel mount/unmount, toast enter/exit, command palette open.

### CSS Transition Defaults
- Hover/active states: `140ms ease`
- Background color changes: `200ms ease`
- Opacity fades: `200ms ease`

### Orchestration
- **Staggered List Reveals:** History rows, agent cards, skill rows cascade with 30ms delay.
- **Panel Mount:** Fade-in + translateY(4px) → translateY(0), 200ms spring.
- **Toast Enter:** translateX(16px) + opacity(0) → translateX(0) + opacity(1), spring.

### Perpetual Micro-Interactions
- **Live Indicator Pulse:** Traces count badge pulses opacity (1 → 0.6 → 1) every 2s.
- **Streaming Cursor Blink:** Typing indicator `|` blinks at 1s steps(1) interval.
- **Skeleton Shimmer:** Continuous gradient sweep at 1.25s, infinite loop.

### Performance Constraints
- Animate exclusively `transform` and `opacity`. Never animate `top`, `left`, `width`, `height`.
- No JavaScript-driven animation loops — CSS animations only.
- `will-change` used sparingly, only on elements that animate frequently.

### Banned Motion
- Linear easing — always use spring or ease-out.
- Scroll-jacking or smooth-scroll hijacking.
- Parallax effects. Custom cursors.

## 7. Anti-Patterns (Banned)

### Typography
- Inter font — use Geist exclusively
- Generic serif fonts (Times New Roman, Georgia, Garamond, Palatino)
- Gradient text on large headers
- All-caps headings exceeding 8 characters

### Color
- Pure black (#000000) — use Deep Slate Ink (#0F172A) or Canvas Base Dark (#0B1120)
- Neon/outer glow shadows on buttons or cards
- Oversaturated accents (keep saturation below 80%)
- Purple/blue neon aesthetic ("AI Purple")
- Warm/cool gray mixing — commit to Slate family

### Layout
- 3-column equal card feature rows
- Centered Hero sections
- Overlapping elements (absolute-position stacking)
- Horizontal scroll on mobile
- `calc()` width hacks — use Grid fractions

### Content
- Emojis anywhere in the UI
- AI copywriting cliches ("Elevate", "Seamless", "Unleash", "Next-Gen", "Supercharge")
- Filler UI text: "Scroll to explore", "Swipe down", scroll arrows, bouncing chevrons
- Generic placeholder names ("John Doe", "Acme", "Nexus")
- Fake round numbers ("99.99% uptime", "50% faster")
- Broken Unsplash links — use inline SVG icons or no decorative images

### Interaction
- Custom mouse cursors
- Scroll-jacking
- Linear easing on interactive elements
- Circular spinners for loading states — use skeleton loaders
- Floating labels on inputs

## 8. Data Interaction Architecture

### State Management Topology

```
┌─────────────────────────────────────────────────────────┐
│  Zustand Stores (Global Singletons)                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────┐  │
│  │ settings │ │   chat   │ │    ui    │ │agentConfig│  │
│  │ Store    │ │  Store   │ │  Store   │ │  Store    │  │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └─────┬─────┘  │
│       │             │            │              │        │
│  localStorage  localStorage  localStorage   memory      │
└───────┼─────────────┼────────────┼──────────────┼───────┘
        │             │            │              │
┌───────┼─────────────┼────────────┼──────────────┼───────┐
│  Custom Hooks (API-Bound Data)                          │
│  ┌──────────────┐ ┌────────────┐ ┌──────────────────┐   │
│  │useWorkspace  │ │useObserv-  │ │useSkillsMgmt     │   │
│  │Catalog       │ │ability     │ │useCredentials    │   │
│  │useToolCatalog│ │            │ │useMcpDrafts      │   │
│  │useAgentFiles │ │            │ │                  │   │
│  └──────┬───────┘ └─────┬──────┘ └────────┬─────────┘   │
│         │                │                 │             │
│         ▼                ▼                 ▼             │
│  ┌─────────────────────────────────────────────────┐    │
│  │  anyagentClient.ts (REST + OpenAI Streaming)    │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

### Data Flow Patterns

1. **Read-on-mount:** Hooks fetch data when settings change (baseUrl, agentId).
   Loading → Ready/Error state machine. Manual refresh buttons, no auto-polling.
2. **Optimistic mutations:** Save → immediate UI update → toast on success/error.
   Rollback on failure with error toast.
3. **Streaming:** OpenAI Responses API with incremental delta callbacks.
   Stream events buffered (max 80) for live display. Stage events loaded post-run.
4. **Persistence:** localStorage for settings, conversations, eval datasets.
   No server-side session state — fully client-driven.
5. **Derived state:** `useMemo` for filtered/computed views (command palette items,
   nav groups, connection comparisons). Never store derived state in stores.

## 9. Page-by-Page Design Specifications

### 9.1 Home Page (Use Mode)

**Layout:** Split-screen asymmetric. Left: chat panel (1.1fr). Right: live stream (0.9fr).
Above: trace table full-width. Below: 2-column asymmetric overview (NOT 3-column equal cards).

**Data Interactions:**
- Chat messages from `chatStore` (localStorage-persisted conversations)
- Streaming via OpenAI Responses API with delta callbacks
- Trace rows derived from `streamEvents` + `stageEvents`
- Conversation CRUD: new, select, rename, delete

**Key States:**
- `catalogStatus !== "ready"` → Setup wizard empty state with CTA to Settings
- `isRunning` → Disable composer submit, show streaming cursor in assistant bubble
- Empty conversations → Welcome message with agent instructions

**Optimization Notes:**
- Trace table uses monospace font for response IDs and latency values
- Stream events capped at 80 entries (ring buffer) to prevent DOM bloat
- Chat log auto-scrolls on new content via scrollIntoView
- Conversation strip uses horizontal scroll with snap points on mobile

### 9.2 Home Page (Build Mode)

**Layout:** Full-width metric grid (4-col) top. Below: asymmetric 2-column grid —
left: configuration checklist panel. Right: build signals panel.

**Data Interactions:**
- Agent detail from `useWorkspaceCatalog` hook
- Skill/MCP/Tool counts derived from workspace catalog
- File existence check from `useAgentFiles`
- Credentials count from `useCredentials`
- Admin health status from server `/healthz`

**Key States:**
- Loading → Skeleton shimmer matching metric-card layout
- Agent not selected → Prompt to select agent in Settings
- All files exist + tools loaded → "healthy" indicator

**Optimization Notes:**
- Metric grid uses `repeat(4, minmax(0, 1fr))` — collapses to 2-col at 768px
- Checklist rows are interactive buttons navigating to respective Build tabs
- Build signals panel is read-only derived summary — no mutations

### 9.3 Agents Page

**Layout:** 2-section. Top: Agent directory as flexible card grid
`repeat(auto-fit, minmax(240px, 1fr))`. Bottom (Build mode only): Create Agent form panel.

**Data Interactions:**
- `listAgents()` via workspace catalog hook — returns agent summaries
- Agent selection → `updateSettings("agentId", value)` → triggers catalog refresh
- Create agent form → POST `/admin/workspace/agents` with ID, instructions, tools
- Validation: agent ID must match `^[a-zA-Z0-9._-]+$`

**Key States:**
- `agents.length === 0` → Empty state with "Create your first agent" CTA
- `agentCreateStatus === "Creating"` → Button spinner + disabled form
- Success → Toast + auto-select new agent + refresh catalog

### 9.4 Sessions Page

**Layout:** Full-width metric strip (3 metrics). Below: Run history list panel.

**Data Interactions:**
- Runs from `useObservability` hook filtered by agent/session
- `selectObservabilityRun(responseId)` loads summary for selected run
- Manual refresh via nonce increment triggers re-fetch

**Key States:**
- No runs → Empty state with "Start session" CTA navigating to Home
- Run selected → Active highlight row with monospace response_id
- Refresh in progress → Button spinner on Refresh button

### 9.5 Observability Page

**Layout:** Complex multi-panel. Top: 4-col metric grid (runs, events, tools, errors).
Middle: asymmetric 2-col — left: timeline/trace panel (1.1fr). Right: filters + tool stats (0.9fr).
Bottom: error list panel full-width.

**Data Interactions:**
- `loadObservabilityRuns()` — paginated with limit/window filters
- `loadObservabilityMetrics()` — aggregated counts and latencies
- `loadObservabilityTools()` — per-tool call stats
- `loadObservabilityErrors()` — error items with source/type/message
- `loadObservabilityTimeline()` — chronological event stream
- `loadObservabilityTrace(traceId)` — deep trace inspection
- Filters: window (all/hour/day), sources, statuses, tool name, limit

**Key States:**
- No runs → Empty state with "Run a session first" guidance
- Trace selected → Expanded trace panel with event waterfall
- Filters active → Filtered counts in metric cards, filtered lists below
- Error items → Color-coded by severity (error=red, warning=amber, denied=red)

**Optimization Notes:**
- Timeline events use virtualized list for 500+ items
- Metric values in monospace `Geist Mono` for alignment
- Tool stats table sortable by call count, error count, avg duration
- Iteration suggestions panel shows actionable next steps based on telemetry

### 9.6 Evaluations Page

**Layout:** Top: metric strip (latency, error count). Below: asymmetric 2-col —
left: run list for seed promotion. Right: evaluation configuration panel.

**Data Interactions:**
- Runs from observability hook (reused data, not re-fetched)
- Eval datasets persisted in localStorage via `evalStore`
- Promote run → copies input/output pair into eval seed dataset
- Inspect run → navigates to observability with run pre-selected

**Key States:**
- No eval seeds → Empty state with "Promote your first run" CTA
- Run promoted → Success toast + seed count increment
- Latency/error metrics derived from observability data

### 9.7 Prompts Page

**Layout:** Asymmetric 2-col. Left: prompt input + preview trigger (1.1fr).
Right: assembled prompt bundle display (0.9fr).

**Data Interactions:**
- `previewPromptBundle(settings, input)` — POST to server, returns assembled prompt
- Input synced with `chatStore.input` (shared with Home page composer)
- Bundle display shows: system prompt, skill injections, MCP context, tool definitions

**Key States:**
- No preview loaded → Placeholder with "Enter input and click Preview"
- Loading → Skeleton shimmer in bundle panel
- Bundle loaded → Collapsible sections for each prompt fragment
- Error → Inline error message with retry CTA

### 9.8 Configure Page

**Layout:** Tabbed sub-navigation within page. Active tab renders one of:
ConnectionPanel, CreateAgentPanel, EffectiveConfigPanel, ToolCatalogSection.
Grid: `minmax(0, 1.35fr) minmax(340px, 0.65fr)` — wider editor column.

**Data Interactions:**
- Agent config CRUD via `updateAgentConfig()` — model, sandbox, tools, spawn rules
- File editing via `updateAgentFile()` with sha256 optimistic locking
- Connection draft → test → apply flow with 3-step state machine
- Tool catalog refresh after config save
- Config version history via `configVersionStore` (diff snapshots)

**Key States:**
- `agentConfigStatus === "Saving"` → Button spinner + disabled form
- `hasConnectionDraftChanges` → Highlight "Apply" button as primary
- `saveStatus` for file editor → "Saved" chip or error message
- Config diff available → Show "Compare versions" button

**Optimization Notes:**
- Form fields use controlled inputs with debounced validation
- Tool catalog section uses checkbox grid for tool selection
- File editor uses monospace textarea with 430px min-height
- Config version snapshots enable undo/compare workflows

### 9.9 Skills Page

**Layout:** Full-width. Top: install form panel (channel selector + fields).
Below: skill list with toggle switches and update indicators.

**Data Interactions:**
- `listSkills()` → skill summaries with enabled/selected/path/hash
- Install channels: `skills.sh` (registry), `github`, `local_upload`
- `installAgentSkill()` / `importAgentSkill()` for new skills
- `toggleSkillEnabled()` → updates disabled_skill_paths in agent config
- `toggleSkillSelection()` → updates default_selected skills
- `checkAgentSkillUpdate()` / `applyAgentSkillUpdate()` for updates
- `saveSkillSelection()` → persists selection to server

**Key States:**
- `skillImportStatus === "Installing"` → Button spinner + disabled form
- Skill has update available → Amber "Update" badge + apply button
- Skill disabled → Muted row with strikethrough name
- No skills → Empty state with install guidance

### 9.10 MCP Page

**Layout:** Full-width panel. Draft list with add/remove/edit rows.
Each draft row: name, transport selector, URL/command, credential, enabled toggle.

**Data Interactions:**
- Drafts stored in memory (derived from agent's mcp.json file)
- `addMcpDraft()` → appends empty draft row
- `updateMcpDraft(index, field, value)` → updates specific draft field
- `removeMcpDraft(index)` → removes draft row
- `saveMcpDrafts()` → serializes to JSON, writes via `updateAgentFile()`
- Transport types: `streamable_http`, `stdio`, `sse`

**Key States:**
- `mcpStatus === "Saving"` → Button spinner on Save
- `mcpDraftsEditable === false` → Read-only display (no agent selected)
- Empty drafts → "Add your first MCP server" CTA
- Invalid draft (missing name/url) → Inline validation error

### 9.11 Tools Page

**Layout:** Asymmetric 2-col. Left: effective tool catalog (resolved tools for agent).
Right: available tools (all workspace tools). Both as scrollable lists.

**Data Interactions:**
- `listTools()` → effective catalog (filtered by agent config)
- `listAvailableTools()` → full workspace catalog (admin endpoint)
- `toggleRequestedTool(name)` → adds/removes from agentToolsText CSV
- Tool items show: name, kind, description, decision (allow/deny), reason

**Key States:**
- `toolCatalogStatus === "Loading"` → Skeleton list
- Tool denied → Red "denied" chip with reason tooltip
- Tool allowed → Green "allowed" chip
- No tools → Empty state with "Configure tools in agent config"

### 9.12 Credentials Page

**Layout:** Full-width. Top: create credential form. Below: credential list table.

**Data Interactions:**
- `listCredentials()` → credential refs with id, kind, scope
- `setCredential()` → POST new credential (id, kind, value, scope)
- `deleteCredential(id)` → DELETE with confirmation dialog
- Scope: global or agent-scoped (uses current agentId)
- Kinds: `bearer_token`, `api_key`, `oauth_client`, custom

**Key States:**
- `credentialStatus === "Saving"` → Button spinner
- Credential created → Success toast + list refresh
- Delete confirmation → `window.confirm()` dialog
- No credentials → Empty state with security guidance

### 9.13 Audit Page

**Layout:** Full-width. Top: error summary metrics. Below: audit event list
with timeline visualization.

**Data Interactions:**
- Errors from `useObservability` hook (shared with Observability page)
- Runs with audit references linked to policy denials
- Timeline events filtered by `source === "audit"`
- Inspect run → loads full observability trace

**Key States:**
- No audit events → "Clean audit trail" success state
- Errors present → Color-coded list (error=red, warning=amber)
- Run inspection → Navigates to Observability with trace pre-loaded

### 9.14 Debug Page

**Layout:** Full-width. Stage events replay list + prompt bundle inspector.

**Data Interactions:**
- `stageEvents` from chatStore (loaded after run completes via `listEvents()`)
- `promptBundle` from `previewPromptBundle()` — shows assembled prompt
- Events displayed as formatted JSON with type/seq/tool_name highlighting

**Key States:**
- No stage events → "Run a session to see replay events"
- Events loaded → Scrollable JSON list with syntax highlighting
- Prompt bundle loaded → Collapsible sections per fragment

### 9.15 Files Page

**Layout:** Asymmetric 2-col. Left: file kind selector tabs + monospace editor (1.35fr).
Right: file metadata panel (0.65fr) showing path, sha256, exists status.

**Data Interactions:**
- `listAgentFiles()` → returns agents_md, agent_yaml, mcp_json files
- `updateAgentFile(kind, text, expectedSha256)` → PUT with optimistic lock
- File kinds toggled via `enabledFileKinds` array
- Editor text synced with active file kind selection
- Save triggers sha256 comparison for conflict detection

**Key States:**
- `saveStatus === "Saving"` → Button spinner
- `saveStatus === "Conflict"` → Error with "Reload and retry" CTA
- File doesn't exist → "Create" button instead of "Save"
- Editor dirty (unsaved changes) → Dot indicator on tab

### 9.16 Settings Page

**Layout:** Full-width stacked sections. Connection panel (URL, API key, admin key).
Below: agent/model/session settings. Below: admin health panel.

**Data Interactions:**
- Connection draft → test → apply 3-step flow
- `testConnectionDraft()` → attempts `listAgents()` + `getAgent()` on draft
- `applyConnectionDraft()` → commits draft to active settings (localStorage)
- `resetStoredSettings()` → clears all localStorage with confirmation
- Admin health: parallel fetch of `/healthz`, storage health, credential capabilities

**Key States:**
- `hasConnectionDraftChanges` → "Apply" button highlighted as primary
- `connectionTestStatus === "Testing"` → Button spinner on Test
- Test success → Green "Connected" chip with agent count
- Test failure → Error message in status field
- Admin loaded → Health/storage/credential panels populated

## 10. Frontend Optimization Strategy

### Component Architecture Improvements

**Current Issue:** `StudioApp.tsx` is a 1185-line god-component that instantiates ALL hooks
and passes 20+ props to each page via prop-drilling.

**Recommended Pattern:**
1. **Colocate hooks with pages** — each page should call its own data hooks directly.
   Pages import stores and hooks themselves rather than receiving everything from parent.
2. **Zustand selectors** — use fine-grained selectors to prevent unnecessary re-renders.
   `useSettingsStore((s) => s.baseUrl)` instead of destructuring entire store.
3. **Lazy hook activation** — hooks should only fetch when their page is active.
   Current pattern fetches ALL data on mount regardless of active tab.

### Render Performance

- **React.lazy + Suspense** already in place — keep preloading on hover/focus.
- **Virtualization** for lists exceeding 50 items (observability timeline, stream events).
- **Memo boundaries** at page level — `React.memo()` each page component.
- **Stable references** — wrap callbacks in `useCallback` at hook level, not component level.
- **Event buffer cap** — stream events ring buffer at 80 items prevents unbounded growth.

### Data Fetching Optimization

- **Deduplication:** Multiple pages share observability data — single hook instance suffices.
  Use Zustand middleware or React context to share fetched data across pages.
- **Stale-while-revalidate:** Show cached data immediately, refresh in background on mount.
- **Abort signals:** Cancel in-flight requests when navigating away from page.
- **Batch requests:** Admin health loads 3 endpoints in `Promise.all()` — good pattern,
  apply same to workspace catalog (agents + detail + skills in parallel).

### Bundle Size

- **HeroUI tree-shaking:** Import only used components (`@heroui/react` may bundle entire lib).
  Switch to individual imports: `@heroui/button`, `@heroui/card`, `@heroui/chip`.
- **Lucide tree-shaking:** Already using named imports — confirmed optimal.
- **Code splitting:** Pages already lazy-loaded. Consider splitting heavy hooks
  (useObservability is complex) into their own chunks.

### Accessibility Compliance

- Focus-visible rings on all interactive elements (2px Signal Blue, 2px offset)
- ARIA labels on icon-only buttons and inputs
- `role="main"`, `role="navigation"`, `role="dialog"` landmarks
- `aria-live="polite"` on status regions
- Keyboard navigation: Arrow keys in sidebar, Escape for command palette
- Color contrast ratio >= 4.5:1 for text (WCAG AA)

## 11. Stitch Screen Generation Guide

When prompting Stitch to generate individual screens, use this template:

```
Generate a [PAGE_NAME] screen for AnyAgent Studio.

Visual: Cockpit-dense dashboard (density 7), dark mode primary canvas (#0B1120).
Font: Geist sans + Geist Mono for numbers. No Inter, no serif.
Accent: Signal Blue (#3B82F6) — single accent only.
Layout: [SPECIFIC_GRID from Section 9.x]
Components: [LIST from Section 4]
State: [ACTIVE_STATE — what data is loaded, what's empty]
Data: [DESCRIBE what the screen displays and mutates]

Constraints:
- No 3-column equal cards. No centered heroes.
- No emojis. No neon glows. No gradient text.
- Monospace for all numeric values and hashes.
- 44px minimum touch targets. Focus rings on all interactive elements.
```

### Screen Priority Order for Generation

1. **Home (Use)** — primary user-facing screen, chat + live stream
2. **Observability** — most complex layout, validates grid system
3. **Configure** — tests form patterns and editor layouts
4. **Settings** — validates connection flow and form states
5. **Agents** — tests card grid and create form patterns
6. **Skills** — tests list + toggle + install form composition
7. **Sessions** — tests table/list patterns with selection state
8. **Tools** — tests dual-panel comparison layout
9. **MCP** — tests dynamic form row add/remove pattern
10. **Credentials** — tests CRUD table pattern
11. **Evaluations** — tests metric + promotion workflow
12. **Prompts** — tests preview/inspector pattern
13. **Audit** — tests timeline visualization
14. **Debug** — tests JSON display and event replay
15. **Files** — tests code editor pattern
16. **Home (Build)** — tests dashboard summary pattern
