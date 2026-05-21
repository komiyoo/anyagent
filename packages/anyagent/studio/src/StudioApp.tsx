import {
  Button,
  Card,
  Chip,
  Input,
  Separator,
  Tabs,
  TextArea,
} from "@heroui/react";
import {
  Activity,
  BarChart3,
  Bot,
  Braces,
  Bug,
  Cable,
  ChevronDown,
  Code2,
  Database,
  FileText,
  FlaskConical,
  Home,
  KeyRound,
  Layers3,
  MessageSquareText,
  PanelLeftClose,
  PanelLeftOpen,
  Play,
  PackagePlus,
  Puzzle,
  RefreshCw,
  Rocket,
  Search,
  Send,
  Settings,
  SlidersHorizontal,
  Sparkles,
  SquarePen,
  Timer,
  Wrench,
} from "lucide-react";
import { FormEvent, ForwardRefExoticComponent, RefAttributes, useEffect, useMemo, useState } from "react";
import { LucideProps } from "lucide-react";
import {
  AgentDetail,
  AgentFileKind,
  AgentWorkspaceFile,
  AgentSummary,
  ChatMessage,
  McpServerDraft,
  ObservabilitySummary,
  ObservabilityRunItem,
  ObservabilityTimelineEvent,
  ObservabilityMetrics,
  ObservabilityToolStats,
  ObservabilityErrorItem,
  ObservabilityTrace,
  ObservabilitySource,
  SkillSummary,
  SkillChannel,
  StudioDebugEvent,
  StudioSettings,
  applyAgentSkillUpdate,
  buildMcpJson,
  checkAgentSkillUpdate,
  createAgent,
  CredentialRef,
  deleteCredential,
  getAdminAgent,
  getAgent,
  importAgentSkill,
  installAgentSkill,
  listAvailableTools,
  listCredentials,
  listAgentFiles,
  listAgents,
  listEvents,
  listSkills,
  listTools,
  loadObservabilitySummary,
  loadObservabilityRuns,
  loadObservabilityTimeline,
  loadObservabilityMetrics,
  loadObservabilityTools,
  loadObservabilityErrors,
  loadObservabilityTrace,
  parseMcpDrafts,
  previewPromptBundle,
  runChat,
  setCredential,
  ToolCatalog,
  updateAgentConfig,
  updateAgentFile,
  updateAgentSkills,
} from "./anyagentClient";

const defaultSettings: StudioSettings = {
  baseUrl: import.meta.env.VITE_ANYAGENT_BASE_URL ?? window.location.origin,
  apiKey: import.meta.env.VITE_ANYAGENT_API_KEY ?? "anyagent-dev-key",
  adminKey: import.meta.env.VITE_ANYAGENT_ADMIN_KEY ?? import.meta.env.VITE_ANYAGENT_API_KEY ?? "anyagent-dev-key",
  model: import.meta.env.VITE_ANYAGENT_MODEL ?? "gpt-5.5",
  agentId: import.meta.env.VITE_ANYAGENT_AGENT_ID ?? "main",
  sessionKey: `studio-${new Date().toISOString().slice(0, 10)}`,
};

const sampleMcpDrafts: McpServerDraft[] = [
  {
    name: "amap",
    enabled: true,
    transport: "streamable_http",
    url: "http://127.0.0.1:8000/mcp",
    command: "",
    credentialId: "cred_amap",
  },
];

const sampleSkillMarkdown = `---
name: sales-discovery
description: Helps qualify customer discovery notes.
metadata:
  short-description: Sales discovery helper
---

Use this skill when the user is preparing, summarizing, or following up on a customer discovery conversation.
`;

const compactJson = (value: unknown) => JSON.stringify(value, null, 2);

const shortHash = (value?: string) => (value ? value.slice(0, 12) : "none");

const csvToList = (value: string) =>
  value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);

const fileLabels: Record<AgentFileKind, string> = {
  agents_md: "AGENTS.md",
  agent_yaml: "agent.yaml",
  mcp_json: "mcp.json",
};

function displayText(value: unknown, fallback = "unknown"): string {
  if (typeof value === "string" && value.trim()) {
    return value;
  }
  if (value && typeof value === "object") {
    const candidate = value as { display_name?: unknown; name?: unknown; stable_id?: unknown; short_description?: unknown };
    for (const item of [candidate.display_name, candidate.name, candidate.stable_id, candidate.short_description]) {
      if (typeof item === "string" && item.trim()) {
        return item;
      }
    }
    return JSON.stringify(value);
  }
  return fallback;
}

function eventSummary(event: StudioDebugEvent): { title: string; detail: string; meta: string } {
  const payload = event as Record<string, unknown>;
  const type = typeof payload.type === "string" ? payload.type : "event";
  const seq = typeof payload.seq === "number" ? `#${payload.seq}` : "";
  if (type === "anyagent.tool.planned") {
    return {
      title: `Tool planned: ${displayText(payload.tool_name, "tool")}`,
      detail: compactJson(payload.arguments ?? {}),
      meta: seq,
    };
  }
  if (type === "anyagent.tool.result") {
    return {
      title: `Tool result: ${displayText(payload.tool_name, "tool")}`,
      detail: compactJson({ status: payload.status, output: payload.output, error: payload.error }),
      meta: seq,
    };
  }
  if (type === "anyagent.command.planned") {
    return {
      title: "Command planned",
      detail: compactJson({ command: payload.command, workdir: payload.workdir, timeout_ms: payload.timeout_ms }),
      meta: seq,
    };
  }
  if (type === "anyagent.command.result") {
    return {
      title: "Command result",
      detail: compactJson({ exit_code: payload.exit_code, stdout: payload.stdout, stderr: payload.stderr }),
      meta: seq,
    };
  }
  if (type === "anyagent.prompt.context") {
    return {
      title: "Prompt context assembled",
      detail: compactJson({
        fragments: payload.fragment_kinds,
        selected_skill_ids: payload.selected_skill_ids,
        prompt_cache_key: payload.prompt_cache_key,
      }),
      meta: seq,
    };
  }
  if (type === "anyagent.done") {
    return { title: "Run completed", detail: "Done", meta: seq };
  }
  return { title: type, detail: compactJson(event), meta: seq };
}

function numericValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function eventType(event: StudioDebugEvent): string {
  const payload = event as Record<string, unknown>;
  return typeof payload.type === "string" ? payload.type : "event";
}

function firstNumber(payload: Record<string, unknown>, keys: string[]): number | null {
  for (const key of keys) {
    const direct = numericValue(payload[key]);
    if (direct !== null) {
      return direct;
    }
    const segments = key.split(".");
    let cursor: unknown = payload;
    for (const segment of segments) {
      cursor = cursor && typeof cursor === "object" ? (cursor as Record<string, unknown>)[segment] : undefined;
    }
    const nested = numericValue(cursor);
    if (nested !== null) {
      return nested;
    }
  }
  return null;
}

function formatCount(value: number): string {
  return Number.isFinite(value) ? value.toLocaleString() : "-";
}

function formatMs(value: number | null): string {
  return value === null ? "-" : `${Math.round(value)} ms`;
}

function timelineMeta(event: ObservabilityTimelineEvent): string {
  return [event.source, event.status, event.tool_name, event.trace_id ? `trace ${event.trace_id}` : ""].filter(Boolean).join(" · ");
}

type NavItem = {
  icon: ForwardRefExoticComponent<Omit<LucideProps, "ref"> & RefAttributes<SVGSVGElement>>;
  label: string;
  target: StudioTab;
  shortcut?: string;
  count?: string;
};

type StudioMode = "use" | "build";
type StudioTab = "chat" | "observability" | "debug" | "configure" | "skills" | "mcp" | "tools" | "files";

const navGroupsByMode: Record<StudioMode, Array<{ label: string; items: NavItem[] }>> = {
  use: [
    {
      label: "Application",
      items: [
        { icon: Home, label: "Home", target: "chat" },
        { icon: Bot, label: "Agents", target: "chat" },
        { icon: MessageSquareText, label: "Sessions", target: "observability" },
        { icon: BarChart3, label: "Observability", target: "observability", count: "0" },
      ],
    },
    {
      label: "Improve",
      items: [
        { icon: Database, label: "Evaluations", target: "observability" },
        { icon: FlaskConical, label: "Prompts", target: "debug" },
      ],
    },
    {
      label: "Workspace",
      items: [{ icon: Settings, label: "Settings", target: "configure" }],
    },
  ],
  build: [
    {
      label: "Build",
      items: [
        { icon: Home, label: "Home", target: "configure" },
        { icon: Bot, label: "Agents", target: "configure" },
        { icon: SlidersHorizontal, label: "Configure", target: "configure" },
        { icon: PackagePlus, label: "Skills", target: "skills" },
      ],
    },
    {
      label: "Capabilities",
      items: [
        { icon: Puzzle, label: "MCP", target: "mcp" },
        { icon: Wrench, label: "Tools", target: "tools" },
        { icon: KeyRound, label: "Credentials", target: "configure" },
      ],
    },
    {
      label: "Debug",
      items: [
        { icon: Bug, label: "Debug", target: "debug" },
        { icon: FileText, label: "Files", target: "files" },
        { icon: Code2, label: "Settings", target: "configure" },
      ],
    },
  ],
};

function useWorkspaceCatalog(settings: StudioSettings) {
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [agentDetail, setAgentDetail] = useState<AgentDetail | null>(null);
  const [skills, setSkills] = useState<SkillSummary[]>([]);
  const [status, setStatus] = useState("idle");

  async function refresh() {
    setStatus("loading");
    try {
      const nextAgents = await listAgents(settings, true);
      setAgents(nextAgents);
      const nextAgentId = settings.agentId || nextAgents[0]?.agent_id || "";
      let detail: AgentDetail | null = null;
      try {
        detail = await getAgent(settings, nextAgentId);
      } catch {
        detail = await getAdminAgent(settings, nextAgentId);
      }
      const nextSkills = await listSkills(settings, nextAgentId);
      setAgentDetail(detail);
      setSkills(nextSkills);
      setStatus("ready");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "catalog failed");
      setAgents([]);
      setAgentDetail(null);
      setSkills([]);
    }
  }

  useEffect(() => {
    void refresh();
  }, [settings.baseUrl, settings.apiKey, settings.agentId]);

  return { agents, agentDetail, skills, status, refresh };
}

function fileByKind(files: AgentWorkspaceFile[], kind: AgentFileKind): AgentWorkspaceFile | undefined {
  return files.find((file) => file.kind === kind);
}

export function StudioApp() {
  const [settings, setSettings] = useState<StudioSettings>(defaultSettings);
  const [studioMode, setStudioMode] = useState<StudioMode>("use");
  const [activeTab, setActiveTab] = useState<StudioTab>("chat");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "welcome",
      role: "assistant",
      content: "AnyAgent Studio is ready. Pick an agent, inspect its pack, then run a client session.",
    },
  ]);
  const [input, setInput] = useState("用当前 agent 的配置介绍一下你能做什么。");
  const [isRunning, setIsRunning] = useState(false);
  const [activeResponseId, setActiveResponseId] = useState<string>("");
  const [selectedResponseId, setSelectedResponseId] = useState<string>("");
  const [streamEvents, setStreamEvents] = useState<StudioDebugEvent[]>([]);
  const [stageEvents, setStageEvents] = useState<StudioDebugEvent[]>([]);
  const [observabilitySummary, setObservabilitySummary] = useState<ObservabilitySummary | null>(null);
  const [observabilityRuns, setObservabilityRuns] = useState<ObservabilityRunItem[]>([]);
  const [observabilityMetrics, setObservabilityMetrics] = useState<ObservabilityMetrics | null>(null);
  const [observabilityTools, setObservabilityTools] = useState<ObservabilityToolStats[]>([]);
  const [observabilityErrors, setObservabilityErrors] = useState<ObservabilityErrorItem[]>([]);
  const [observabilityTimeline, setObservabilityTimeline] = useState<ObservabilityTimelineEvent[]>([]);
  const [observabilityTrace, setObservabilityTrace] = useState<ObservabilityTrace | null>(null);
  const [observabilityTraceId, setObservabilityTraceId] = useState("");
  const [observabilitySource, setObservabilitySource] = useState<"all" | ObservabilitySource>("all");
  const [observabilityStatus, setObservabilityStatus] = useState<"all" | "error" | "warning" | "success" | "denied">("all");
  const [observabilityToolFilter, setObservabilityToolFilter] = useState("");
  const [observabilityRefreshNonce, setObservabilityRefreshNonce] = useState(0);
  const [observabilityWindow, setObservabilityWindow] = useState<"all" | "hour" | "day">("all");
  const [observabilityLimit, setObservabilityLimit] = useState(20);
  const [promptBundle, setPromptBundle] = useState<Record<string, unknown> | null>(null);
  const [agentFiles, setAgentFiles] = useState<AgentWorkspaceFile[]>([]);
  const [activeFileKind, setActiveFileKind] = useState<AgentFileKind>("agents_md");
  const [editorText, setEditorText] = useState("");
  const [enabledFileKinds, setEnabledFileKinds] = useState<AgentFileKind[]>(["agents_md", "agent_yaml", "mcp_json"]);
  const [saveStatus, setSaveStatus] = useState("Not loaded");
  const [newAgentId, setNewAgentId] = useState("sales-agent");
  const [newAgentTools, setNewAgentTools] = useState("");
  const [newAgentInstructions, setNewAgentInstructions] = useState("你是一个面向业务团队的 AnyAgent agent。");
  const [agentCreateStatus, setAgentCreateStatus] = useState("Ready");
  const [skillDirectoryName, setSkillDirectoryName] = useState("sales-discovery");
  const [skillMarkdown, setSkillMarkdown] = useState(sampleSkillMarkdown);
  const [skillImportStatus, setSkillImportStatus] = useState("Ready");
  const [skillChannel, setSkillChannel] = useState<SkillChannel>("skills.sh");
  const [skillPackage, setSkillPackage] = useState("vercel-labs/agent-skills");
  const [skillName, setSkillName] = useState("web-design-guidelines");
  const [skillGithubRef, setSkillGithubRef] = useState("main");
  const [skillGithubPath, setSkillGithubPath] = useState("");
  const [skillSelection, setSkillSelection] = useState<string[]>([]);
  const [disabledSkillPaths, setDisabledSkillPaths] = useState<string[]>([]);
  const [skillUpdateStatus, setSkillUpdateStatus] = useState<Record<string, string>>({});
  const [skillSelectionStatus, setSkillSelectionStatus] = useState("Ready");
  const [agentExposed, setAgentExposed] = useState(true);
  const [agentModelDefault, setAgentModelDefault] = useState("");
  const [agentModelProvider, setAgentModelProvider] = useState("openai");
  const [agentModelBaseUrlEnv, setAgentModelBaseUrlEnv] = useState("OPENAI_BASE_URL");
  const [agentModelApiKeyEnv, setAgentModelApiKeyEnv] = useState("OPENAI_API_KEY");
  const [agentSandboxMode, setAgentSandboxMode] = useState("disabled");
  const [agentToolsText, setAgentToolsText] = useState("");
  const [agentSpawnText, setAgentSpawnText] = useState("");
  const [agentConfigStatus, setAgentConfigStatus] = useState("Ready");
  const [toolCatalog, setToolCatalog] = useState<ToolCatalog | null>(null);
  const [availableTools, setAvailableTools] = useState<ToolCatalog | null>(null);
  const [toolCatalogStatus, setToolCatalogStatus] = useState("Not loaded");
  const [availableToolsStatus, setAvailableToolsStatus] = useState("Not loaded");
  const [mcpStatus, setMcpStatus] = useState("Draft ready");
  const [mcpDrafts, setMcpDrafts] = useState<McpServerDraft[]>(sampleMcpDrafts);
  const [mcpDraftsEditable, setMcpDraftsEditable] = useState(true);
  const [credentials, setCredentials] = useState<CredentialRef[]>([]);
  const [credentialId, setCredentialId] = useState("cred_amap");
  const [credentialKind, setCredentialKind] = useState("bearer_token");
  const [credentialValue, setCredentialValue] = useState("");
  const [credentialScope, setCredentialScope] = useState<"global" | "agent">("agent");
  const [credentialStatus, setCredentialStatus] = useState("Not loaded");
  const { agents, agentDetail, skills, status, refresh } = useWorkspaceCatalog(settings);

  const selectedSkillCount = useMemo(() => skills.filter((skill) => skill.selected).length, [skills]);
  const mcpJson = useMemo(() => buildMcpJson(mcpDrafts), [mcpDrafts]);
  const allDebugEvents = useMemo(() => [...streamEvents, ...stageEvents], [streamEvents, stageEvents]);
  const observability = useMemo(() => {
    const userTurns = messages.filter((message) => message.role === "user");
    const assistantTurns = messages.filter((message) => message.role === "assistant" && message.content.trim());
    const eventPayloads = allDebugEvents.map((event) => event as Record<string, unknown>);
    const eventTypes = allDebugEvents.map(eventType);
    const toolCalls = eventTypes.filter((type) => type === "anyagent.tool.planned" || type === "anyagent.tool.result").length;
    const mcpCalls = eventPayloads.filter((payload) => {
      const type = typeof payload.type === "string" ? payload.type : "";
      const server = typeof payload.server_label === "string" || typeof payload.mcp_server_label === "string";
      return type.includes("mcp") || server;
    }).length;
    const selectedSkillIds = new Set<string>();
    eventPayloads.forEach((payload) => {
      const ids = payload.selected_skill_ids;
      if (Array.isArray(ids)) {
        ids.forEach((id) => {
          if (typeof id === "string" && id.trim()) {
            selectedSkillIds.add(id);
          }
        });
      }
    });
    const inputChars = userTurns.reduce((total, message) => total + message.content.length, 0);
    const outputChars = assistantTurns.reduce((total, message) => total + message.content.length, 0);
    const inputTokens = eventPayloads.reduce(
      (total, payload) => total + (firstNumber(payload, ["usage.input_tokens", "usage.prompt_tokens", "input_tokens"]) ?? 0),
      0,
    );
    const outputTokens = eventPayloads.reduce(
      (total, payload) => total + (firstNumber(payload, ["usage.output_tokens", "usage.completion_tokens", "output_tokens"]) ?? 0),
      0,
    );
    const cachedTokens = eventPayloads.reduce(
      (total, payload) =>
        total + (firstNumber(payload, ["usage.input_tokens_details.cached_tokens", "usage.prompt_tokens_details.cached_tokens", "cached_tokens"]) ?? 0),
      0,
    );
    const firstTokenLatency = eventPayloads
      .map((payload) => firstNumber(payload, ["first_token_ms", "latency.first_token_ms", "ttft_ms"]))
      .find((value): value is number => value !== null) ?? null;
    const totalLatency = eventPayloads
      .map((payload) => firstNumber(payload, ["total_latency_ms", "latency.total_ms", "duration_ms", "elapsed_ms"]))
      .filter((value): value is number => value !== null)
      .at(-1) ?? null;
    return {
      runCount: activeResponseId ? 1 : 0,
      turnCount: userTurns.length,
      eventCount: allDebugEvents.length,
      toolCalls,
      mcpCalls,
      skillViews: selectedSkillIds.size || selectedSkillCount,
      inputChars,
      outputChars,
      avgInputChars: userTurns.length ? Math.round(inputChars / userTurns.length) : 0,
      avgOutputChars: assistantTurns.length ? Math.round(outputChars / assistantTurns.length) : 0,
      inputTokens,
      outputTokens,
      cachedTokens,
      firstTokenLatency,
      totalLatency,
    };
  }, [activeResponseId, allDebugEvents, messages, selectedSkillCount]);
  const displayObservability = useMemo(() => {
    if (!observabilitySummary) {
      return observability;
    }
    return {
      ...observability,
      runCount: observabilityMetrics?.run_count ?? (observabilitySummary.response_id ? 1 : observability.runCount),
      turnCount: observabilitySummary.turn_count ?? observability.turnCount,
      eventCount: observabilityMetrics?.event_count ?? observabilitySummary.event_count ?? observability.eventCount,
      toolCalls: observabilityMetrics?.tool_call_count ?? observabilitySummary.tool_call_count ?? observability.toolCalls,
      mcpCalls: observabilityMetrics?.mcp_call_count ?? observabilitySummary.mcp_call_count ?? observability.mcpCalls,
      skillViews: observabilitySummary.skill_view_count ?? observability.skillViews,
      inputChars: observabilitySummary.input_chars ?? observability.inputChars,
      outputChars: observabilitySummary.output_chars ?? observability.outputChars,
      inputTokens: observabilityMetrics?.input_tokens ?? observabilitySummary.input_tokens ?? observability.inputTokens,
      outputTokens: observabilityMetrics?.output_tokens ?? observabilitySummary.output_tokens ?? observability.outputTokens,
      cachedTokens: observabilityMetrics?.cached_input_tokens ?? observabilitySummary.cached_input_tokens ?? observability.cachedTokens,
      firstTokenLatency: observabilityMetrics?.first_token_latency_ms ?? observabilitySummary.first_token_latency_ms ?? observability.firstTokenLatency,
      totalLatency: observabilityMetrics?.max_response_latency_ms ?? observabilitySummary.total_response_latency_ms ?? observability.totalLatency,
    };
  }, [observability, observabilityMetrics, observabilitySummary]);
  const selectedRun = useMemo(
    () => observabilityRuns.find((run) => run.response_id === selectedResponseId) ?? observabilityRuns[0] ?? null,
    [selectedResponseId, observabilityRuns],
  );
  const filteredObservabilityTools = useMemo(() => {
    const needle = observabilityToolFilter.trim().toLowerCase();
    return needle ? observabilityTools.filter((tool) => tool.tool_name.toLowerCase().includes(needle)) : observabilityTools;
  }, [observabilityToolFilter, observabilityTools]);
  const filteredObservabilityErrors = useMemo(() => {
    const needle = observabilityToolFilter.trim().toLowerCase();
    return observabilityErrors.filter((error) => {
      if (observabilitySource !== "all" && error.source !== observabilitySource) return false;
      if (observabilityStatus !== "all" && error.status !== observabilityStatus && error.payload?.status !== observabilityStatus) return false;
      if (!needle) return true;
      return [error.tool_name, error.type, error.message, error.trace_id].some((value) => String(value ?? "").toLowerCase().includes(needle));
    });
  }, [observabilityErrors, observabilitySource, observabilityStatus, observabilityToolFilter]);
  const filteredObservabilityTimeline = useMemo(() => {
    const needle = observabilityToolFilter.trim().toLowerCase();
    return observabilityTimeline.filter((event) => {
      if (observabilitySource !== "all" && event.source !== observabilitySource) return false;
      if (observabilityStatus !== "all" && event.status !== observabilityStatus && event.level !== observabilityStatus) return false;
      if (!needle) return true;
      return [event.tool_name, event.type, event.message, event.trace_id, event.audit_ref].some((value) =>
        String(value ?? "").toLowerCase().includes(needle),
      );
    });
  }, [observabilitySource, observabilityStatus, observabilityTimeline, observabilityToolFilter]);
  const iterationSuggestions = useMemo(() => {
    const suggestions: Array<{ title: string; detail: string; target: StudioTab }> = [];
    if (displayObservability.totalLatency !== null && displayObservability.totalLatency > 3000) {
      suggestions.push({
        title: "Review latency",
        detail: `Total response time is ${formatMs(displayObservability.totalLatency)} for the selected run.`,
        target: "debug",
      });
    }
    if (displayObservability.inputTokens + displayObservability.outputTokens > 6000) {
      suggestions.push({
        title: "Trim prompt context",
        detail: `${formatCount(displayObservability.inputTokens + displayObservability.outputTokens)} tokens were used.`,
        target: "files",
      });
    }
    if (displayObservability.toolCalls > 4 || displayObservability.mcpCalls > 2) {
      suggestions.push({
        title: "Inspect tool routing",
        detail: `${formatCount(displayObservability.toolCalls + displayObservability.mcpCalls)} tool/MCP calls were observed.`,
        target: "tools",
      });
    }
    if (displayObservability.skillViews > Math.max(3, selectedSkillCount)) {
      suggestions.push({
        title: "Prune skill disclosure",
        detail: `${formatCount(displayObservability.skillViews)} skills were disclosed or selected.`,
        target: "skills",
      });
    }
    if (displayObservability.avgInputChars > 2000 || displayObservability.avgOutputChars > 4000) {
      suggestions.push({
        title: "Check turn length",
        detail: `Average turn length is ${formatCount(displayObservability.avgInputChars)} input chars and ${formatCount(displayObservability.avgOutputChars)} output chars.`,
        target: "observability",
      });
    }
    return suggestions.length
      ? suggestions
      : [{ title: "No optimization flags", detail: "Selected run metrics are within the current thresholds.", target: "observability" as StudioTab }];
  }, [displayObservability, selectedSkillCount]);
  const navGroups = useMemo(
    () =>
      navGroupsByMode[studioMode].map((group) => ({
        ...group,
        items: group.items.map((item) => ({
          ...item,
          count: item.label === "Observability" ? String(streamEvents.length + stageEvents.length) : item.count,
        })),
      })),
    [studioMode, streamEvents.length, stageEvents.length],
  );

  function updateSettings<K extends keyof StudioSettings>(key: K, value: StudioSettings[K]) {
    setSettings((previous) => ({ ...previous, [key]: value }));
  }

  async function loadAgentFiles() {
    if (!settings.agentId) {
      return;
    }
    setSaveStatus("Loading files");
    try {
      const files = await listAgentFiles(settings, settings.agentId);
      setAgentFiles(files);
      const active = fileByKind(files, activeFileKind) ?? files[0];
      setEditorText(active?.text ?? "");
      const mcpFile = fileByKind(files, "mcp_json");
      if (mcpFile?.text) {
        try {
          const drafts = parseMcpDrafts(mcpFile.text);
          if (drafts.length > 0) {
            setMcpDrafts(drafts);
            setMcpStatus(`Loaded ${drafts.length} server${drafts.length === 1 ? "" : "s"}`);
          } else {
            setMcpDrafts([]);
            setMcpStatus("Loaded empty mcp.json");
          }
          setMcpDraftsEditable(true);
        } catch (error) {
          setMcpStatus(error instanceof Error ? `mcp.json parse failed: ${error.message}` : "mcp.json parse failed");
          setMcpDraftsEditable(false);
        }
      } else if (mcpFile?.exists === false) {
        setMcpDrafts([]);
        setMcpStatus("No mcp.json");
        setMcpDraftsEditable(true);
      }
      setSaveStatus("Ready");
    } catch (error) {
      setAgentFiles([]);
      setEditorText("");
      setSaveStatus(error instanceof Error ? error.message : "Load failed");
    }
  }

  async function saveActiveFile() {
    if (!enabledFileKinds.includes(activeFileKind)) {
      setSaveStatus(`${fileLabels[activeFileKind]} is disabled in Studio`);
      return;
    }
    const current = fileByKind(agentFiles, activeFileKind);
    setSaveStatus("Saving");
    try {
      const updated = await updateAgentFile(settings, settings.agentId, activeFileKind, editorText, current?.sha256);
      setAgentFiles((files) => {
        const without = files.filter((file) => file.kind !== activeFileKind);
        return [...without, updated].sort((left, right) => left.kind.localeCompare(right.kind));
      });
      setEditorText(updated.text ?? "");
      setSaveStatus(`Saved ${fileLabels[activeFileKind]}`);
      await refresh();
    } catch (error) {
      setSaveStatus(error instanceof Error ? error.message : "Save failed");
    }
  }

  function switchActiveFile(kind: AgentFileKind) {
    setActiveFileKind(kind);
    setEditorText(fileByKind(agentFiles, kind)?.text ?? "");
  }

  function toggleFileKind(kind: AgentFileKind) {
    setEnabledFileKinds((current) =>
      current.includes(kind) ? current.filter((item) => item !== kind) : Array.from(new Set([...current, kind])),
    );
  }

  useEffect(() => {
    void loadAgentFiles();
  }, [settings.baseUrl, settings.adminKey, settings.agentId]);

  useEffect(() => {
    setSkillSelection(
      skills
        .filter((skill) => skill.selected)
        .map((skill) => displayText(skill.name, skill.stable_id ?? ""))
        .filter(Boolean),
    );
    setDisabledSkillPaths(
      skills
        .filter((skill) => skill.enabled === false)
        .map((skill) => (typeof skill.path === "string" ? skill.path : skill.stable_id ?? ""))
        .filter(Boolean),
    );
  }, [skills]);

  useEffect(() => {
    setAgentExposed(agentDetail?.exposed ?? true);
    setAgentModelDefault(agentDetail?.model?.default ?? agentDetail?.model_default ?? settings.model);
    setAgentModelProvider(agentDetail?.model?.provider ?? agentDetail?.model_provider ?? "openai");
    setAgentModelBaseUrlEnv(agentDetail?.model?.base_url_env ?? agentDetail?.model_base_url_env ?? "OPENAI_BASE_URL");
    setAgentModelApiKeyEnv(agentDetail?.model?.api_key_env ?? agentDetail?.model_api_key_env ?? "OPENAI_API_KEY");
    setAgentSandboxMode(agentDetail?.sandbox?.mode ?? agentDetail?.sandbox_mode ?? "disabled");
    setAgentToolsText((agentDetail?.tools?.requested_tool_names ?? agentDetail?.requested_tool_names ?? []).join(", "));
    setAgentSpawnText((agentDetail?.multiagent?.spawn_allow_agent_ids ?? []).join(", "));
  }, [agentDetail]);

  async function submitChat(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || isRunning) {
      return;
    }
    const userMessage: ChatMessage = { id: crypto.randomUUID(), role: "user", content: trimmed };
    const assistantMessage: ChatMessage = { id: crypto.randomUUID(), role: "assistant", content: "" };
    const nextMessages = [...messages, userMessage, assistantMessage];
    setMessages(nextMessages);
    setInput("");
    setIsRunning(true);
    setStreamEvents([]);
    setStageEvents([]);
    setPromptBundle(null);
    setActiveResponseId("");
    setSelectedResponseId("");
    try {
      const result = await runChat(
        settings,
        nextMessages.filter((message) => message.id !== assistantMessage.id),
        (delta) => {
          setMessages((current) =>
            current.map((message) =>
              message.id === assistantMessage.id ? { ...message, content: message.content + delta } : message,
            ),
          );
        },
        (debugEvent) => setStreamEvents((current) => [...current.slice(-79), debugEvent]),
      );
      if (result.responseId) {
        setActiveResponseId(result.responseId);
        setSelectedResponseId(result.responseId);
        const replay = await listEvents(settings, result.responseId);
        setStageEvents(replay);
      }
    } catch (error) {
      setMessages((current) =>
        current.map((message) =>
          message.id === assistantMessage.id
            ? { ...message, content: error instanceof Error ? error.message : "Request failed" }
            : message,
        ),
      );
    } finally {
      setIsRunning(false);
    }
  }

  async function loadPromptPreview() {
    setPromptBundle(null);
    const bundle = await previewPromptBundle(settings, input || "hello");
    setPromptBundle(bundle);
  }

  async function submitCreateAgent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAgentCreateStatus("Creating");
    try {
      const requestedToolNames = newAgentTools
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
      const created = await createAgent(settings, newAgentId, `${newAgentInstructions.trim()}\n`, requestedToolNames);
      setAgentCreateStatus(`Created ${created.agent.agent_id}`);
      updateSettings("agentId", created.agent.agent_id);
      await refresh();
    } catch (error) {
      setAgentCreateStatus(error instanceof Error ? error.message : "Create failed");
    }
  }

  async function submitSkillInstall(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSkillImportStatus(skillChannel === "local_upload" ? "Importing" : "Installing");
    try {
      const installed =
        skillChannel === "local_upload"
          ? await importAgentSkill(settings, settings.agentId, skillDirectoryName, skillMarkdown)
          : await installAgentSkill(settings, settings.agentId, skillChannel, skillPackage, skillName, undefined, false, {
              repo: skillPackage,
              ref: skillGithubRef,
              path: skillGithubPath || skillName,
            });
      setSkillImportStatus(`${skillChannel === "local_upload" ? "Imported" : "Installed"} ${installed.name}`);
      await refresh();
    } catch (error) {
      setSkillImportStatus(error instanceof Error ? error.message : "Skill channel failed");
    }
  }

  function toggleSkillSelection(skill: SkillSummary, checked: boolean) {
    const name = displayText(skill.name, skill.stable_id ?? "");
    if (!name) {
      return;
    }
    setSkillSelection((current) =>
      checked ? Array.from(new Set([...current, name])) : current.filter((item) => item !== name),
    );
  }

  function skillDisableRef(skill: SkillSummary): string {
    return typeof skill.path === "string" && skill.path.trim() ? skill.path : skill.stable_id ?? "";
  }

  function skillDirectoryRef(skill: SkillSummary): string {
    const path = typeof skill.path === "string" ? skill.path : "";
    const segments = path.split("/").filter(Boolean);
    const skillMdIndex = segments.lastIndexOf("SKILL.md");
    if (skillMdIndex > 0) {
      return segments[skillMdIndex - 1];
    }
    return displayText(skill.name, skill.stable_id ?? "");
  }

  function toggleSkillEnabled(skill: SkillSummary, enabled: boolean) {
    const ref = skillDisableRef(skill);
    if (!ref) {
      return;
    }
    setDisabledSkillPaths((current) => (enabled ? current.filter((item) => item !== ref) : Array.from(new Set([...current, ref]))));
    if (!enabled) {
      const name = displayText(skill.name, skill.stable_id ?? "");
      setSkillSelection((current) => current.filter((item) => item !== name && item !== skill.stable_id));
    }
  }

  function toggleRequestedTool(name: string) {
    const current = csvToList(agentToolsText);
    setAgentToolsText(current.includes(name) ? current.filter((item) => item !== name).join(", ") : [...current, name].join(", "));
  }

  async function saveSkillSelection() {
    setSkillSelectionStatus("Saving");
    try {
      const updated = await updateAgentSkills(settings, settings.agentId, skillSelection);
      setSkillSelectionStatus(`Saved ${updated.agent.skills?.default_selected?.length ?? 0} selected`);
      await refresh();
      await loadAgentFiles();
    } catch (error) {
      setSkillSelectionStatus(error instanceof Error ? error.message : "Save failed");
    }
  }

  async function checkSkillUpdate(skill: SkillSummary) {
    const directoryName = skillDirectoryRef(skill);
    if (!directoryName) {
      return;
    }
    setSkillUpdateStatus((current) => ({ ...current, [directoryName]: "Checking" }));
    try {
      const check = await checkAgentSkillUpdate(settings, settings.agentId, directoryName);
      const status = check.updatable
        ? check.update_available
          ? `Update available (${check.channel})`
          : `Up to date (${check.channel})`
        : check.reason || "Not updatable";
      setSkillUpdateStatus((current) => ({ ...current, [directoryName]: status }));
    } catch (error) {
      setSkillUpdateStatus((current) => ({ ...current, [directoryName]: error instanceof Error ? error.message : "Check failed" }));
    }
  }

  async function applySkillUpdate(skill: SkillSummary) {
    const directoryName = skillDirectoryRef(skill);
    if (!directoryName) {
      return;
    }
    setSkillUpdateStatus((current) => ({ ...current, [directoryName]: "Updating" }));
    try {
      const updated = await applyAgentSkillUpdate(settings, settings.agentId, directoryName);
      setSkillUpdateStatus((current) => ({ ...current, [directoryName]: `Updated ${updated.name}` }));
      await refresh();
    } catch (error) {
      setSkillUpdateStatus((current) => ({ ...current, [directoryName]: error instanceof Error ? error.message : "Update failed" }));
    }
  }

  async function saveAgentConfig() {
    setAgentConfigStatus("Saving");
    try {
      const updated = await updateAgentConfig(settings, settings.agentId, {
        exposed: agentExposed,
        model_default: agentModelDefault,
        model_provider: agentModelProvider,
        model_base_url_env: agentModelBaseUrlEnv,
        model_api_key_env: agentModelApiKeyEnv,
        requested_tool_names: csvToList(agentToolsText),
        sandbox_mode: agentSandboxMode,
        spawn_allow_agent_ids: csvToList(agentSpawnText),
        disabled_skill_paths: disabledSkillPaths,
      });
      setAgentConfigStatus(`Saved ${updated.agent.agent_id}`);
      await refresh();
      await loadToolCatalog();
      await loadAgentFiles();
    } catch (error) {
      setAgentConfigStatus(error instanceof Error ? error.message : "Save failed");
    }
  }

  async function loadToolCatalog() {
    if (!settings.agentId) {
      return;
    }
    setToolCatalogStatus("Loading");
    try {
      const catalog = await listTools(settings, settings.agentId, csvToList(agentToolsText));
      setToolCatalog(catalog);
      setToolCatalogStatus(`v${catalog.toolset_version}`);
    } catch (error) {
      setToolCatalog(null);
      setToolCatalogStatus(error instanceof Error ? error.message : "Load failed");
    }
  }

  async function loadCredentials() {
    setCredentialStatus("Loading");
    try {
      const payload = await listCredentials(settings);
      setCredentials(payload.credentials);
      setCredentialStatus(`${payload.credentials.length} saved`);
    } catch (error) {
      setCredentials([]);
      setCredentialStatus(error instanceof Error ? error.message : "Load failed");
    }
  }

  async function loadAvailableTools() {
    setAvailableToolsStatus("Loading");
    try {
      const catalog = await listAvailableTools(settings);
      setAvailableTools(catalog);
      setAvailableToolsStatus(`v${catalog.toolset_version}`);
    } catch (error) {
      setAvailableTools(null);
      setAvailableToolsStatus(error instanceof Error ? error.message : "Load failed");
    }
  }

  async function submitCredential(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCredentialStatus("Saving");
    try {
      const ref = await setCredential(
        settings,
        credentialId.trim(),
        credentialKind.trim(),
        credentialValue,
        credentialScope,
        settings.agentId,
      );
      setCredentialStatus(`Saved ${ref.credential_id}`);
      setCredentialValue("");
      await loadCredentials();
    } catch (error) {
      setCredentialStatus(error instanceof Error ? error.message : "Save failed");
    }
  }

  async function removeCredential(id: string) {
    setCredentialStatus("Deleting");
    try {
      await deleteCredential(settings, id);
      await loadCredentials();
    } catch (error) {
      setCredentialStatus(error instanceof Error ? error.message : "Delete failed");
    }
  }

  async function selectObservabilityRun(responseId: string) {
    setSelectedResponseId(responseId);
    setActiveResponseId(responseId);
    setStageEvents([]);
    setObservabilitySummary(null);
    setObservabilityTimeline([]);
    try {
      const [summary, replay, timeline] = await Promise.all([
        loadObservabilitySummary(settings, responseId),
        listEvents(settings, responseId),
        loadObservabilityTimeline(settings, { responseId, limit: 200 }),
      ]);
      setObservabilitySummary(summary);
      setStageEvents(replay);
      setObservabilityTimeline(timeline.events ?? []);
    } catch {
      setStageEvents([]);
      setObservabilitySummary(null);
      setObservabilityTimeline([]);
    }
  }

  async function inspectObservabilityTrace(traceId: string) {
    const normalized = traceId.trim();
    if (!normalized) {
      setObservabilityTrace(null);
      return;
    }
    setObservabilityTraceId(normalized);
    try {
      const trace = await loadObservabilityTrace(settings, normalized, 500);
      setObservabilityTrace(trace);
      setObservabilityTimeline(trace?.events ?? []);
    } catch {
      setObservabilityTrace(null);
    }
  }

  useEffect(() => {
    const now = Date.now();
    const createdAfterMs =
      observabilityWindow === "hour" ? now - 60 * 60 * 1000 : observabilityWindow === "day" ? now - 24 * 60 * 60 * 1000 : undefined;
    const filters = {
      agentId: settings.agentId,
      sessionKey: settings.sessionKey,
      createdAfterMs,
      limit: observabilityLimit,
    };
    void loadObservabilityRuns(settings, filters)
      .then((payload) => {
        const runs = payload.runs ?? [];
        setObservabilityRuns(runs);
        setSelectedResponseId((current) => current || activeResponseId || runs[0]?.response_id || "");
      })
      .catch(() => setObservabilityRuns([]));
    void Promise.all([
      loadObservabilityMetrics(settings, filters),
      loadObservabilityTools(settings, filters),
      loadObservabilityErrors(settings, { ...filters, limit: 50 }),
      loadObservabilityTimeline(settings, { ...filters, limit: 200 }),
    ])
      .then(([metrics, tools, errors, timeline]) => {
        setObservabilityMetrics(metrics);
        setObservabilityTools(tools.tools ?? []);
        setObservabilityErrors(errors.errors ?? []);
        setObservabilityTimeline(timeline.events ?? []);
      })
      .catch(() => {
        setObservabilityMetrics(null);
        setObservabilityTools([]);
        setObservabilityErrors([]);
        setObservabilityTimeline([]);
      });
  }, [
    settings.baseUrl,
    settings.apiKey,
    settings.agentId,
    settings.sessionKey,
    activeResponseId,
    observabilityWindow,
    observabilityLimit,
    observabilityRefreshNonce,
  ]);

  useEffect(() => {
    if (!selectedResponseId) {
      setObservabilitySummary(null);
      return;
    }
    void loadObservabilitySummary(settings, selectedResponseId)
      .then((summary) => setObservabilitySummary(summary))
      .catch(() => setObservabilitySummary(null));
    void loadObservabilityTimeline(settings, { responseId: selectedResponseId, limit: 200 })
      .then((timeline) => setObservabilityTimeline(timeline.events ?? []))
      .catch(() => setObservabilityTimeline([]));
  }, [settings.baseUrl, settings.apiKey, selectedResponseId]);

  useEffect(() => {
    void loadToolCatalog();
  }, [settings.baseUrl, settings.apiKey, settings.agentId, settings.sessionKey, agentToolsText]);

  useEffect(() => {
    void loadCredentials();
  }, [settings.baseUrl, settings.adminKey, settings.agentId]);

  useEffect(() => {
    void loadAvailableTools();
  }, [settings.baseUrl, settings.adminKey]);

  function updateMcpDraft(index: number, patch: Partial<McpServerDraft>) {
    setMcpDrafts((current) => current.map((item, itemIndex) => (itemIndex === index ? { ...item, ...patch } : item)));
  }

  function addMcpDraft() {
    setMcpDrafts((current) => [
      ...current,
      {
        name: `server-${current.length + 1}`,
        enabled: true,
        transport: "streamable_http",
        url: "",
        command: "",
        credentialId: "",
      },
    ]);
  }

  function removeMcpDraft(index: number) {
    setMcpDrafts((current) => current.filter((_, itemIndex) => itemIndex !== index));
  }

  async function saveMcpDrafts() {
    if (!mcpDraftsEditable) {
      setMcpStatus("Fix mcp.json in source editor before form save");
      return;
    }
    const current = fileByKind(agentFiles, "mcp_json");
    setMcpStatus("Saving");
    try {
      const updated = await updateAgentFile(settings, settings.agentId, "mcp_json", `${mcpJson}\n`, current?.sha256);
      setAgentFiles((files) => {
        const without = files.filter((file) => file.kind !== "mcp_json");
        return [...without, updated].sort((left, right) => left.kind.localeCompare(right.kind));
      });
      if (activeFileKind === "mcp_json") {
        setEditorText(updated.text ?? "");
      }
      setMcpStatus("Saved mcp.json");
      await refresh();
    } catch (error) {
      setMcpStatus(error instanceof Error ? error.message : "Save failed");
    }
  }

  const traceRows = [
    {
      name: settings.agentId || "main",
      latest: activeResponseId || "No runs",
      traces: streamEvents.length + stageEvents.length,
      errors: status === "ready" ? "0%" : "-",
      p50: "-",
      p99: "-",
      description: "OpenAI-compatible client session",
    },
  ];

  return (
    <main className={`studio-shell ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
      <aside className="sidebar">
        <div className="brand-row">
          <div className="mode-switcher" aria-label="Studio mode">
            <strong>AnyAgent</strong>
            <ChevronDown size={16} />
            <div className="mode-options" role="group" aria-label="Mode switcher">
              <button
                className={studioMode === "use" ? "active" : ""}
                type="button"
                onClick={() => {
                  setStudioMode("use");
                  setActiveTab("chat");
                }}
                title="Use mode"
              >
                Use
              </button>
              <button
                className={studioMode === "build" ? "active" : ""}
                type="button"
                onClick={() => {
                  setStudioMode("build");
                  setActiveTab("configure");
                }}
                title="Build mode"
              >
                Build
              </button>
            </div>
          </div>
          <button
            className="sidebar-toggle"
            type="button"
            aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            onClick={() => setSidebarCollapsed((current) => !current)}
          >
            {sidebarCollapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
          </button>
        </div>

        <nav className="side-nav" aria-label="Primary">
          {navGroups.map((group, groupIndex) => (
            <div className="nav-group" key={groupIndex}>
              <span className="nav-group-label">{group.label}</span>
              {group.items.map((item) => (
                <button
                  className={`nav-item ${activeTab === item.target ? "active" : ""}`}
                  type="button"
                  key={item.label}
                  title={item.label}
                  onClick={() => setActiveTab(item.target)}
                >
                  <item.icon size={16} />
                  <span>{item.label}</span>
                  {item.shortcut ? <kbd>{item.shortcut}</kbd> : null}
                  {item.count ? <em>{item.count}</em> : null}
                </button>
              ))}
            </div>
          ))}
        </nav>

        <div className="sidebar-footer">
          <button className="nav-item" type="button">
            <Settings size={16} />
            <span>Settings</span>
          </button>
          <div>
            <strong>Personal</strong>
            <small>{settings.agentId || "No agent"}</small>
          </div>
        </div>
      </aside>

      <section className="workspace">
        <header className="workspace-header">
          <span>{studioMode === "use" ? "Use Mode" : "Build Mode"}</span>
        </header>

        <div className="project-header">
          <div className="project-icon">
            <Bot size={22} />
          </div>
          <div>
            <h1>{settings.agentId || "Personal"}</h1>
            <p>ID {settings.agentId || "unselected"} · {status}</p>
          </div>
          <div className="project-actions">
            <button className="quick-pill" type="button">
              <Activity size={16} />
              <span>Traces</span>
              <strong>{streamEvents.length + stageEvents.length}/5000</strong>
            </button>
            <button className="quick-pill" type="button">
              <Layers3 size={16} />
              <span>Studio quickstart</span>
            </button>
            <button className="quick-pill" type="button">
              <Activity size={16} />
              <span>Tracing quickstart</span>
            </button>
            <button className="quick-pill" type="button">
              <Database size={16} />
              <span>Evaluation quickstart</span>
            </button>
          </div>
        </div>

        <Tabs className="tabs" selectedKey={activeTab} onSelectionChange={(key) => setActiveTab(String(key) as StudioTab)}>
          <Tabs.List aria-label="Studio sections">
            <Tabs.Tab id="chat">
              <span className="tab-label">
                <MessageSquareText size={16} /> Client
              </span>
            </Tabs.Tab>
            <Tabs.Tab id="observability">
              <span className="tab-label">
                <BarChart3 size={16} /> Observability
              </span>
            </Tabs.Tab>
            <Tabs.Tab id="debug">
              <span className="tab-label">
                <Bug size={16} /> Debug
              </span>
            </Tabs.Tab>
            <Tabs.Tab id="configure">
              <span className="tab-label">
                <Wrench size={16} /> Configure
              </span>
            </Tabs.Tab>
            <Tabs.Tab id="skills">
              <span className="tab-label">
                <PackagePlus size={16} /> Skills
              </span>
            </Tabs.Tab>
            <Tabs.Tab id="mcp">
              <span className="tab-label">
                <Puzzle size={16} /> MCP
              </span>
            </Tabs.Tab>
            <Tabs.Tab id="tools">
              <span className="tab-label">
                <Wrench size={16} /> Tools
              </span>
            </Tabs.Tab>
            <Tabs.Tab id="files">
              <span className="tab-label">
                <FileText size={16} /> Files
              </span>
            </Tabs.Tab>
          </Tabs.List>

          <Tabs.Panel id="chat">
            <section className="section-block">
              <div className="section-title">
                <Activity size={17} />
                <h2>Tracing</h2>
                <span>Last 7 Days</span>
              </div>
              <div className="trace-table">
                <div className="trace-row header">
                  <span>Name</span>
                  <span>Most Recent Run</span>
                  <span>Trace Count</span>
                  <span>Error Rate</span>
                  <span>P50 Latency</span>
                  <span>P99 Latency</span>
                  <span>Description</span>
                </div>
                {traceRows.map((row) => (
                  <div className="trace-row" key={row.name}>
                    <strong>{row.name}</strong>
                    <span>{row.latest}</span>
                    <span>{row.traces}</span>
                    <span className="success-badge">{row.errors}</span>
                    <span>{row.p50}</span>
                    <span>{row.p99}</span>
                    <span>{row.description}</span>
                  </div>
                ))}
              </div>
            </section>

            <div className="main-grid">
              <Card className="panel chat-panel">
                <Card.Header className="panel-header">
                  <div className="panel-title">
                    <MessageSquareText size={18} />
                    <span>Client session</span>
                  </div>
                  <Chip size="sm" variant="soft" color={isRunning ? "warning" : "success"}>
                    {isRunning ? "running" : "ready"}
                  </Chip>
                </Card.Header>
                <Card.Content className="panel-content">
                  <div className="chat-log">
                    {messages.map((message) => (
                      <article className={`message ${message.role}`} key={message.id}>
                        <span>{message.role}</span>
                        <p>{message.content || (isRunning && message.role === "assistant" ? "..." : "")}</p>
                      </article>
                    ))}
                  </div>
                  <form className="composer" onSubmit={submitChat}>
                    <TextArea
                      rows={3}
                      value={input}
                      onChange={(event) => setInput(event.target.value)}
                      placeholder="Send a message as a user of the selected agent"
                      aria-label="Message"
                    />
                    <Button type="submit" variant="primary" isDisabled={isRunning}>
                      <Send size={16} />
                      Send
                    </Button>
                  </form>
                </Card.Content>
              </Card>

              <Card className="panel">
                <Card.Header className="panel-header">
                  <div className="panel-title">
                    <Activity size={18} />
                    <span>Live stream</span>
                  </div>
                </Card.Header>
                <Card.Content className="panel-content">
                  <div className="event-list">
                    {streamEvents.length === 0 ? (
                      <p className="empty">OpenAI Responses stream events appear here.</p>
                    ) : (
                      streamEvents.map((event, index) => (
                        <pre key={`${event.type}-${index}`}>{compactJson(event)}</pre>
                      ))
                    )}
                  </div>
                </Card.Content>
              </Card>
            </div>

            <section className="overview-grid">
              <Card className="overview-card">
                <Card.Content className="overview-content">
                  <div className="empty-icon">
                    <Sparkles size={27} />
                  </div>
                  <h3>Skills</h3>
                  <p>{selectedSkillCount} selected from {skills.length} available skills</p>
                </Card.Content>
              </Card>
              <Card className="overview-card">
                <Card.Content className="overview-content">
                  <div className="empty-icon">
                    <Cable size={27} />
                  </div>
                  <h3>MCP</h3>
                  <p>{mcpDrafts.length} draft server{mcpDrafts.length === 1 ? "" : "s"} in the current config</p>
                </Card.Content>
              </Card>
              <Card className="overview-card">
                <Card.Content className="overview-content">
                  <div className="empty-icon">
                    <Braces size={27} />
                  </div>
                  <h3>Prompt source</h3>
                  <p>AGENTS.md hash {shortHash(agentDetail?.agents_md?.sha256)}</p>
                </Card.Content>
              </Card>
            </section>
          </Tabs.Panel>

          <Tabs.Panel id="observability">
            <section className="section-block">
              <div className="section-title">
                <BarChart3 size={17} />
                <h2>Observability</h2>
                <span>{settings.agentId || "main"} · current session</span>
              </div>
              <div className="metric-grid">
                <Card className="metric-card">
                  <Card.Content>
                    <span>Runs</span>
                    <strong>{formatCount(displayObservability.runCount)}</strong>
                    <small>{selectedResponseId || "No response yet"}</small>
                  </Card.Content>
                </Card>
                <Card className="metric-card">
                  <Card.Content>
                    <span>Turns</span>
                    <strong>{formatCount(displayObservability.turnCount)}</strong>
                    <small>{formatCount(displayObservability.avgInputChars)} avg input chars</small>
                  </Card.Content>
                </Card>
                <Card className="metric-card">
                  <Card.Content>
                    <span>Tool Calls</span>
                    <strong>{formatCount(displayObservability.toolCalls)}</strong>
                    <small>{formatCount(observabilityTools.length)} unique tools · {formatCount(displayObservability.eventCount)} events</small>
                  </Card.Content>
                </Card>
                <Card className="metric-card">
                  <Card.Content>
                    <span>MCP Calls</span>
                    <strong>{formatCount(displayObservability.mcpCalls)}</strong>
                    <small>{mcpDrafts.length} configured draft servers</small>
                  </Card.Content>
                </Card>
                <Card className="metric-card">
                  <Card.Content>
                    <span>Skill Views</span>
                    <strong>{formatCount(displayObservability.skillViews)}</strong>
                    <small>{selectedSkillCount} default selected</small>
                  </Card.Content>
                </Card>
                <Card className="metric-card">
                  <Card.Content>
                    <span>LLM Tokens</span>
                    <strong>{formatCount(displayObservability.inputTokens + displayObservability.outputTokens)}</strong>
                    <small>
                      in {formatCount(displayObservability.inputTokens)} · out {formatCount(displayObservability.outputTokens)} · cache{" "}
                      {formatCount(displayObservability.cachedTokens)}
                    </small>
                  </Card.Content>
                </Card>
                <Card className="metric-card">
                  <Card.Content>
                    <span>First Token</span>
                    <strong>{formatMs(displayObservability.firstTokenLatency)}</strong>
                    <small>from streamed/model events when available</small>
                  </Card.Content>
                </Card>
                <Card className="metric-card">
                  <Card.Content>
                    <span>Errors</span>
                    <strong>{formatCount(observabilityMetrics?.error_count ?? observabilityErrors.length)}</strong>
                    <small>{formatMs(displayObservability.totalLatency)} max response</small>
                  </Card.Content>
                </Card>
                <Card className="metric-card">
                  <Card.Content>
                    <span>Avg Response</span>
                    <strong>{formatMs(observabilityMetrics?.avg_response_latency_ms ?? null)}</strong>
                    <small>{formatMs(displayObservability.totalLatency)} max response</small>
                  </Card.Content>
                </Card>
                <Card className="metric-card">
                  <Card.Content>
                    <span>Timeline</span>
                    <strong>{formatCount(observabilityTimeline.length)}</strong>
                    <small>{selectedResponseId || "workspace scope"}</small>
                  </Card.Content>
                </Card>
                <Card className="metric-card">
                  <Card.Content>
                    <span>Total Response</span>
                    <strong>{formatMs(displayObservability.totalLatency)}</strong>
                    <small>from streamed/model events when available</small>
                  </Card.Content>
                </Card>
              </div>
            </section>

            <div className="main-grid observability-grid">
              <Card className="panel">
                <Card.Header className="panel-header">
                  <div className="panel-title">
                    <MessageSquareText size={18} />
                    <span>History</span>
                  </div>
                  <Chip size="sm" variant="soft" color={observabilityRuns.length ? "success" : "default"}>
                    {observabilityRuns.length ? `${observabilityRuns.length} runs` : "empty"}
                  </Chip>
                </Card.Header>
                <Card.Content className="panel-content">
                  <div className="filter-row">
                    <select
                      className="native-select"
                      aria-label="Observability time window"
                      value={observabilityWindow}
                      onChange={(event) => setObservabilityWindow(event.target.value as "all" | "hour" | "day")}
                    >
                      <option value="all">All time</option>
                      <option value="hour">Last hour</option>
                      <option value="day">Last 24 hours</option>
                    </select>
                    <Input
                      aria-label="Run limit"
                      type="number"
                      min={1}
                      max={100}
                      value={String(observabilityLimit)}
                      onChange={(event) => setObservabilityLimit(Math.max(1, Math.min(100, Number(event.target.value) || 20)))}
                    />
                    <Button size="sm" variant="ghost" isIconOnly aria-label="Refresh observability" onPress={() => setObservabilityRefreshNonce((value) => value + 1)}>
                      <RefreshCw size={16} />
                    </Button>
                  </div>
                  <div className="filter-row">
                    <Input
                      aria-label="Trace id"
                      placeholder="trace_id"
                      value={observabilityTraceId}
                      onChange={(event) => setObservabilityTraceId(event.target.value)}
                    />
                    <Button size="sm" variant="ghost" onPress={() => void inspectObservabilityTrace(observabilityTraceId)}>
                      Trace
                    </Button>
                  </div>
                  {observabilityTrace ? (
                    <div className="breakdown-list turn-breakdown">
                      <div className="breakdown-row">
                        <span>Trace responses</span>
                        <strong>{observabilityTrace.response_ids.slice(0, 3).join(", ") || "-"}</strong>
                      </div>
                      <div className="breakdown-row">
                        <span>Audit refs</span>
                        <strong>{formatCount(observabilityTrace.audit_refs.length)}</strong>
                      </div>
                    </div>
                  ) : null}
                  <div className="history-list">
                    {observabilityRuns.length === 0 ? (
                      <p className="empty">No run history available for the current agent/session.</p>
                    ) : (
                      observabilityRuns.map((run) => (
                        <button
                          className={`history-row ${run.response_id === selectedRun?.response_id ? "active" : ""}`}
                          key={run.response_id}
                          type="button"
                          onClick={() => void selectObservabilityRun(run.response_id)}
                        >
                          <div>
                            <strong>{run.response_id}</strong>
                            <span>{run.status} · {run.session_key}</span>
                          </div>
                          <p>
                            {run.stream ? "stream" : "non-stream"} · {run.agent_id}
                          </p>
                          <em>{formatCount(Math.max(run.updated_at_ms - run.created_at_ms, 0))} ms</em>
                        </button>
                      ))
                    )}
                  </div>
                </Card.Content>
              </Card>

              <Card className="panel">
                <Card.Header className="panel-header">
                  <div className="panel-title">
                    <Timer size={18} />
                    <span>Aggregation</span>
                  </div>
                </Card.Header>
                <Card.Content className="panel-content">
                  <div className="filter-row">
                    <select
                      className="native-select"
                      aria-label="Telemetry source"
                      value={observabilitySource}
                      onChange={(event) => setObservabilitySource(event.target.value as "all" | ObservabilitySource)}
                    >
                      <option value="all">All sources</option>
                      <option value="run">Run</option>
                      <option value="event">Event</option>
                      <option value="stage">Stage</option>
                      <option value="observability">Log</option>
                      <option value="workspace">Workspace</option>
                      <option value="audit">Audit</option>
                    </select>
                    <select
                      className="native-select"
                      aria-label="Telemetry status"
                      value={observabilityStatus}
                      onChange={(event) => setObservabilityStatus(event.target.value as "all" | "error" | "warning" | "success" | "denied")}
                    >
                      <option value="all">All status</option>
                      <option value="error">Error</option>
                      <option value="warning">Warning</option>
                      <option value="success">Success</option>
                      <option value="denied">Denied</option>
                    </select>
                    <Input
                      aria-label="Telemetry filter"
                      placeholder="tool, trace, audit"
                      value={observabilityToolFilter}
                      onChange={(event) => setObservabilityToolFilter(event.target.value)}
                    />
                  </div>
                  <div className="breakdown-list">
                    {[
                      ["Tool calls", displayObservability.toolCalls],
                      ["MCP calls", displayObservability.mcpCalls],
                      ["Errors", observabilityMetrics?.error_count ?? observabilityErrors.length],
                      ["Skill views", displayObservability.skillViews],
                      ["Input chars", displayObservability.inputChars],
                      ["Output chars", displayObservability.outputChars],
                      ["Avg output chars", displayObservability.avgOutputChars],
                    ].map(([label, value]) => (
                      <div className="breakdown-row" key={String(label)}>
                        <span>{label}</span>
                        <strong>{formatCount(Number(value))}</strong>
                      </div>
                    ))}
                  </div>
                  {observabilitySummary?.turns?.length ? (
                    <div className="breakdown-list turn-breakdown">
                      {observabilitySummary.turns.slice(0, 6).map((turn) => (
                        <div className="breakdown-row" key={turn.index}>
                          <span>Turn {turn.index}</span>
                          <strong>
                            in {formatCount(turn.input_chars ?? 0)} · out {formatCount(turn.output_chars ?? 0)}
                          </strong>
                        </div>
                      ))}
                    </div>
                  ) : null}
                  <Separator />
                  <div className="breakdown-list turn-breakdown">
                    {filteredObservabilityTools.length === 0 ? (
                      <div className="breakdown-row">
                        <span>No tool stats</span>
                        <strong>-</strong>
                      </div>
                    ) : (
                      filteredObservabilityTools.slice(0, 8).map((tool) => (
                        <div className="breakdown-row" key={tool.tool_name}>
                          <span>{tool.tool_name}</span>
                          <strong>
                            {formatCount(tool.result_count)} runs · {formatCount(tool.error_count)} errors · {formatMs(tool.avg_duration_ms ?? null)}
                          </strong>
                        </div>
                      ))
                    )}
                  </div>
                  <Separator />
                  <div className="event-list compact-events">
                    {filteredObservabilityErrors.length === 0 ? (
                      <p className="empty">No normalized errors were returned by the telemetry API.</p>
                    ) : (
                      filteredObservabilityErrors.slice(0, 8).map((error, index) => (
                        <article className="timeline-event" key={`err-${error.response_id}-${error.type}-${index}`}>
                          <div>
                            <strong>{error.type}</strong>
                            <span>
                              {[error.source, error.tool_name, error.trace_id].filter(Boolean).join(" · ")}
                              {error.trace_id ? (
                                <button className="inline-link" type="button" onClick={() => void inspectObservabilityTrace(error.trace_id || "")}>
                                  trace
                                </button>
                              ) : null}
                            </span>
                          </div>
                          <pre>{error.message || compactJson(error.payload ?? {})}</pre>
                        </article>
                      ))
                    )}
                  </div>
                  <Separator />
                  <div className="event-list compact-events">
                    {filteredObservabilityTimeline.length === 0 ? (
                      <p className="empty">Telemetry timeline will populate after Core records run, tool, audit, or stage events.</p>
                    ) : (
                      filteredObservabilityTimeline.slice(0, 14).map((event, index) => {
                        return (
                          <article className="timeline-event" key={`tel-${event.response_id}-${event.seq}-${event.type}-${index}`}>
                            <div>
                              <strong>{event.type}</strong>
                              <span>
                                {timelineMeta(event)}
                                {event.trace_id ? (
                                  <button className="inline-link" type="button" onClick={() => void inspectObservabilityTrace(event.trace_id || "")}>
                                    trace
                                  </button>
                                ) : null}
                              </span>
                            </div>
                            {event.message ? <pre>{event.message}</pre> : null}
                          </article>
                        );
                      })
                    )}
                  </div>
                  <Separator />
                  <div className="suggestion-list">
                    {iterationSuggestions.map((suggestion) => (
                      <button className="suggestion-row" key={suggestion.title} type="button" onClick={() => setActiveTab(suggestion.target)}>
                        <strong>{suggestion.title}</strong>
                        <span>{suggestion.detail}</span>
                      </button>
                    ))}
                  </div>
                </Card.Content>
              </Card>
            </div>
          </Tabs.Panel>

          <Tabs.Panel id="debug">
            <div className="main-grid">
              <Card className="panel">
                <Card.Header className="panel-header">
                  <div className="panel-title">
                    <Bug size={18} />
                    <span>Stage events</span>
                  </div>
                </Card.Header>
                <Card.Content className="panel-content">
                  <div className="event-list">
                    {stageEvents.length === 0 ? (
                      <p className="empty">Run a request, then replay tool and prompt events.</p>
                    ) : (
                      stageEvents.map((event, index) => {
                        const summary = eventSummary(event);
                        return (
                          <article className="timeline-event" key={`${event.seq}-${index}`}>
                            <div>
                              <strong>{summary.title}</strong>
                              <span>{summary.meta}</span>
                            </div>
                            <pre>{summary.detail}</pre>
                          </article>
                        );
                      })
                    )}
                  </div>
                </Card.Content>
              </Card>

              <Card className="panel">
                <Card.Header className="panel-header">
                  <div className="panel-title">
                    <Braces size={18} />
                    <span>Prompt bundle</span>
                  </div>
                  <Button size="sm" variant="secondary" onPress={() => void loadPromptPreview()}>
                    <Play size={16} />
                    Preview
                  </Button>
                </Card.Header>
                <Card.Content className="panel-content">
                  <pre className="json-preview">
                    {promptBundle ? compactJson(promptBundle) : "Preview the rendered AGENTS.md, skill, MCP and tool context bundle."}
                  </pre>
                </Card.Content>
              </Card>
            </div>
          </Tabs.Panel>

          <Tabs.Panel id="configure">
            <div className="main-grid configure-grid">
              <Card className="panel wide-panel compact-panel">
                <Card.Header className="panel-header">
                  <div className="panel-title">
                    <Settings size={18} />
                    <span>Connection</span>
                  </div>
                  <div className="editor-actions">
                    <span>{status}</span>
                    <Button size="sm" variant="secondary" onPress={() => void refresh()}>
                      <RefreshCw size={15} />
                      Refresh
                    </Button>
                  </div>
                </Card.Header>
                <Card.Content className="panel-content">
                  <section className="config-bar">
                    <label className="control-label">
                      <span>Server</span>
                      <Input
                        value={settings.baseUrl}
                        onChange={(event) => updateSettings("baseUrl", event.target.value)}
                        aria-label="Server"
                      />
                    </label>
                    <label className="control-label">
                      <span>API key</span>
                      <Input
                        type="password"
                        value={settings.apiKey}
                        onChange={(event) => updateSettings("apiKey", event.target.value)}
                        aria-label="API key"
                      />
                    </label>
                    <label className="control-label">
                      <span>Admin key</span>
                      <Input
                        type="password"
                        value={settings.adminKey}
                        onChange={(event) => updateSettings("adminKey", event.target.value)}
                        aria-label="Admin key"
                      />
                    </label>
                    <label className="control-label">
                      <span>Model</span>
                      <Input
                        value={settings.model}
                        onChange={(event) => updateSettings("model", event.target.value)}
                        aria-label="Model"
                      />
                    </label>
                    <label className="control-label">
                      <span>Agent</span>
                      <select
                        className="native-select"
                        aria-label="Agent"
                        value={settings.agentId}
                        onChange={(event) => updateSettings("agentId", event.target.value)}
                      >
                        {(agents.length ? agents : [{ agent_id: settings.agentId }]).map((agent) => (
                          <option key={agent.agent_id} value={agent.agent_id}>
                            {agent.agent_id}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="control-label">
                      <span>Session</span>
                      <Input
                        value={settings.sessionKey}
                        onChange={(event) => updateSettings("sessionKey", event.target.value)}
                        aria-label="Session"
                      />
                    </label>
                  </section>
                </Card.Content>
              </Card>

              <Card className="panel wide-panel compact-panel">
                <Card.Header className="panel-header">
                  <div className="panel-title">
                    <SquarePen size={18} />
                    <span>Create agent</span>
                  </div>
                  <span className="status-line">{agentCreateStatus}</span>
                </Card.Header>
                <Card.Content className="panel-content">
                  <form className="agent-create-bar" onSubmit={submitCreateAgent}>
                    <Input
                      aria-label="New agent id"
                      value={newAgentId}
                      onChange={(event) => setNewAgentId(event.target.value)}
                    />
                    <Input
                      aria-label="Requested tools"
                      value={newAgentTools}
                      onChange={(event) => setNewAgentTools(event.target.value)}
                    />
                    <TextArea
                      aria-label="New agent instructions"
                      rows={2}
                      value={newAgentInstructions}
                      onChange={(event) => setNewAgentInstructions(event.target.value)}
                    />
                    <Button type="submit" variant="primary">
                      Create agent
                    </Button>
                  </form>
                </Card.Content>
              </Card>

              <Card className="panel editor-panel">
                <Card.Header className="panel-header">
                  <div className="panel-title">
                    <Bot size={18} />
                    <span>Agent pack source</span>
                  </div>
                  <div className="editor-actions">
                    <span>{saveStatus}</span>
                    <Button size="sm" variant="secondary" onPress={() => void loadAgentFiles()}>
                      <RefreshCw size={15} />
                      Reload
                    </Button>
                    <Button size="sm" variant="primary" onPress={() => void saveActiveFile()}>
                      Save
                    </Button>
                  </div>
                </Card.Header>
                <Card.Content className="panel-content">
                  <div className="file-tabs" role="tablist" aria-label="Agent files">
                    {(["agents_md", "agent_yaml", "mcp_json"] as AgentFileKind[]).map((kind) => {
                      const file = fileByKind(agentFiles, kind);
                      return (
                        <button
                          className={activeFileKind === kind ? "active" : ""}
                          type="button"
                          key={kind}
                          onClick={() => switchActiveFile(kind)}
                        >
                          <span>{fileLabels[kind]}</span>
                          <em>{file?.sha256 ? shortHash(file.sha256) : "new"}</em>
                          <i>{enabledFileKinds.includes(kind) ? "Active" : "Disabled"}</i>
                        </button>
                      );
                    })}
                  </div>
                  <button
                    className={`capsule-toggle file-enable-toggle ${enabledFileKinds.includes(activeFileKind) ? "enabled" : ""}`}
                    type="button"
                    onClick={() => toggleFileKind(activeFileKind)}
                  >
                    {enabledFileKinds.includes(activeFileKind) ? "Active editor" : "Editor disabled"}
                  </button>
                  <div className="file-path">{fileByKind(agentFiles, activeFileKind)?.path ?? "No file loaded"}</div>
                  <TextArea
                    className="source-editor"
                    aria-label={`${fileLabels[activeFileKind]} source`}
                    rows={22}
                    value={editorText}
                    onChange={(event) => setEditorText(event.target.value)}
                    readOnly={!enabledFileKinds.includes(activeFileKind)}
                  />
                </Card.Content>
              </Card>

              <Card className="panel">
                <Card.Header className="panel-header">
                  <div className="panel-title">
                    <Braces size={18} />
                    <span>Effective config</span>
                  </div>
                  <div className="editor-actions">
                    <span>{agentConfigStatus}</span>
                    <Button size="sm" variant="primary" onPress={() => void saveAgentConfig()}>
                      Save config
                    </Button>
                  </div>
                </Card.Header>
                <Card.Content className="panel-content">
                  <div className="config-form">
                    <label className="checkbox-control">
                      <input
                        type="checkbox"
                        checked={agentExposed}
                        onChange={(event) => setAgentExposed(event.target.checked)}
                      />
                      <span>Expose this agent to clients</span>
                    </label>
                    <label className="control-label">
                      <span>Default model</span>
                      <Input
                        aria-label="Default model"
                        value={agentModelDefault}
                        onChange={(event) => {
                          setAgentModelDefault(event.target.value);
                          updateSettings("model", event.target.value);
                        }}
                      />
                    </label>
                    <label className="control-label">
                      <span>Model provider</span>
                      <select
                        className="native-select"
                        aria-label="Model provider"
                        value={agentModelProvider}
                        onChange={(event) => setAgentModelProvider(event.target.value)}
                      >
                        <option value="openai">openai</option>
                      </select>
                    </label>
                    <label className="control-label">
                      <span>API key env</span>
                      <Input
                        aria-label="Model API key env"
                        value={agentModelApiKeyEnv}
                        onChange={(event) => setAgentModelApiKeyEnv(event.target.value)}
                      />
                    </label>
                    <label className="control-label">
                      <span>Base URL env</span>
                      <Input
                        aria-label="Model base URL env"
                        value={agentModelBaseUrlEnv}
                        onChange={(event) => setAgentModelBaseUrlEnv(event.target.value)}
                      />
                    </label>
                    <label className="control-label">
                      <span>Sandbox mode</span>
                      <select
                        className="native-select"
                        aria-label="Sandbox mode"
                        value={agentSandboxMode}
                        onChange={(event) => setAgentSandboxMode(event.target.value)}
                      >
                        <option value="disabled">disabled</option>
                        <option value="opensandbox">opensandbox</option>
                        <option value="external">external</option>
                        <option value="local-unsafe">local-unsafe</option>
                      </select>
                    </label>
                    <label className="control-label">
                      <span>Requested tools</span>
                      <Input
                        aria-label="Requested tools"
                        value={agentToolsText}
                        onChange={(event) => setAgentToolsText(event.target.value)}
                      />
                    </label>
                    <label className="control-label">
                      <span>Spawn allow agents</span>
                      <Input
                        aria-label="Spawn allow agents"
                        value={agentSpawnText}
                        onChange={(event) => setAgentSpawnText(event.target.value)}
                      />
                    </label>
                    <label className="control-label">
                      <span>Disabled skills</span>
                      <Input
                        aria-label="Disabled skills"
                        value={disabledSkillPaths.join(", ")}
                        onChange={(event) => setDisabledSkillPaths(csvToList(event.target.value))}
                      />
                    </label>
                  </div>
                  <div className="metadata-grid stacked">
                    <TextArea
                      aria-label="agent.yaml summary"
                      rows={8}
                      value={compactJson({
                        exposed: agentDetail?.exposed,
                        model: agentDetail?.model ?? {
                          provider: agentDetail?.model_provider,
                          default: agentDetail?.model_default,
                          api_key_env: agentDetail?.model_api_key_env,
                          base_url_env: agentDetail?.model_base_url_env,
                        },
                        sandbox_mode: agentDetail?.sandbox?.mode ?? agentDetail?.sandbox_mode,
                        requested_tool_names: agentDetail?.tools?.requested_tool_names ?? agentDetail?.requested_tool_names,
                        default_selected_skills: agentDetail?.skills?.default_selected ?? agentDetail?.default_selected_skills,
                        spawn_allow_agent_ids: agentDetail?.multiagent?.spawn_allow_agent_ids,
                      })}
                      readOnly
                    />
                    <TextArea
                      aria-label="mcp.json draft"
                      rows={10}
                      value={mcpJson}
                      readOnly
                    />
                  </div>
                  <div className="tool-catalog">
                    <div className="subsection-heading">
                      <span>Effective tools</span>
                      <button type="button" onClick={() => void loadToolCatalog()}>
                        Refresh
                      </button>
                      <em>{toolCatalogStatus}</em>
                    </div>
                    <div className="tool-list">
                      {!toolCatalog || toolCatalog.tools.length === 0 ? (
                        <p className="empty">No tools are currently visible to this agent.</p>
                      ) : (
                        toolCatalog.tools.map((tool) => (
                          <article className="tool-row" key={tool.name}>
                            <div>
                              <strong>{tool.name}</strong>
                              <span>{tool.description || "No description"}</span>
                            </div>
                            <Chip size="sm" variant="soft" color={tool.kind === "command" ? "accent" : "default"}>
                              {tool.kind || tool.reason || "tool"}
                            </Chip>
                          </article>
                        ))
                      )}
                    </div>
                    <div className="subsection-heading">
                      <span>Available tools</span>
                      <button type="button" onClick={() => void loadAvailableTools()}>
                        Refresh
                      </button>
                      <em>{availableToolsStatus}</em>
                    </div>
                    <div className="tool-list">
                      {!availableTools || availableTools.tools.length === 0 ? (
                        <p className="empty">No registered tools found.</p>
                      ) : (
                        availableTools.tools.map((tool) => (
                          <article className="tool-row" key={tool.name}>
                            <div>
                              <strong>{tool.name}</strong>
                              <span>{tool.description || "No description"}</span>
                            </div>
                            <button
                              className={`capsule-toggle ${csvToList(agentToolsText).includes(tool.name) ? "enabled" : ""}`}
                              type="button"
                              onClick={() => toggleRequestedTool(tool.name)}
                            >
                              {csvToList(agentToolsText).includes(tool.name) ? "Enabled" : "Disabled"}
                            </button>
                          </article>
                        ))
                      )}
                    </div>
                  </div>
                </Card.Content>
              </Card>

              <Card className="panel">
                <Card.Header className="panel-header">
                  <div className="panel-title">
                    <Sparkles size={18} />
                    <span>Skills</span>
                  </div>
                  <div className="editor-actions">
                    <span>{skillSelectionStatus}</span>
                    <Button size="sm" variant="secondary" onPress={() => void saveSkillSelection()}>
                      Save selection
                    </Button>
                  </div>
                </Card.Header>
                <Card.Content className="panel-content">
                  <form className="skill-import" onSubmit={submitSkillInstall}>
                    <div className="inline-actions channel-inputs">
                      <select
                        className="native-select"
                        aria-label="Skill channel"
                        value={skillChannel}
                        onChange={(event) => setSkillChannel(event.target.value as SkillChannel)}
                      >
                        <option value="skills.sh">skills.sh</option>
                        <option value="registry">registry</option>
                        <option value="github">github</option>
                        <option value="local_upload">local_upload</option>
                      </select>
                      {skillChannel === "local_upload" ? (
                        <Input
                          aria-label="Skill directory"
                          value={skillDirectoryName}
                          onChange={(event) => setSkillDirectoryName(event.target.value)}
                        />
                      ) : skillChannel === "github" ? (
                        <>
                          <Input
                            aria-label="GitHub repo"
                            value={skillPackage}
                            onChange={(event) => setSkillPackage(event.target.value)}
                          />
                          <Input
                            aria-label="GitHub ref"
                            value={skillGithubRef}
                            onChange={(event) => setSkillGithubRef(event.target.value)}
                          />
                          <Input
                            aria-label="GitHub skill path"
                            value={skillGithubPath}
                            onChange={(event) => setSkillGithubPath(event.target.value)}
                          />
                          <Input
                            aria-label="Skill name"
                            value={skillName}
                            onChange={(event) => setSkillName(event.target.value)}
                          />
                        </>
                      ) : (
                        <>
                          <Input
                            aria-label="Skill package"
                            value={skillPackage}
                            onChange={(event) => setSkillPackage(event.target.value)}
                          />
                          <Input
                            aria-label="Skill name"
                            value={skillName}
                            onChange={(event) => setSkillName(event.target.value)}
                          />
                        </>
                      )}
                      <Button size="sm" variant="primary" type="submit">
                        {skillChannel === "local_upload" ? "Import" : "Install"}
                      </Button>
                    </div>
                    {skillChannel === "local_upload" ? (
                      <TextArea
                        aria-label="SKILL.md"
                        rows={8}
                        value={skillMarkdown}
                        onChange={(event) => setSkillMarkdown(event.target.value)}
                      />
                    ) : null}
                    <span className="status-line">{skillImportStatus}</span>
                  </form>
                  <div className="skill-list">
                    {skills.length === 0 ? (
                      <p className="empty">Installed skills from the selected workspace appear here.</p>
                    ) : (
                      skills.map((skill) => {
                        const directoryName = skillDirectoryRef(skill);
                        return (
                        <div className="skill-row" key={skill.stable_id ?? displayText(skill.path, displayText(skill.name))}>
                          <input
                            aria-label={`Select ${displayText(skill.name, skill.stable_id ?? "skill")}`}
                            checked={skillSelection.includes(displayText(skill.name, skill.stable_id ?? ""))}
                            disabled={disabledSkillPaths.includes(skillDisableRef(skill))}
                            type="checkbox"
                            onChange={(event) => toggleSkillSelection(skill, event.target.checked)}
                          />
                          <div>
                            <strong>{displayText(skill.name, skill.stable_id ?? "skill")}</strong>
                            <span>{displayText(skill.path, skill.stable_id ?? "")}</span>
                            {skillUpdateStatus[directoryName] ? <small>{skillUpdateStatus[directoryName]}</small> : null}
                          </div>
                          <button
                            className={`capsule-toggle ${disabledSkillPaths.includes(skillDisableRef(skill)) ? "" : "enabled"}`}
                            type="button"
                            onClick={() => toggleSkillEnabled(skill, disabledSkillPaths.includes(skillDisableRef(skill)))}
                          >
                            {disabledSkillPaths.includes(skillDisableRef(skill)) ? "Disabled" : "Enabled"}
                          </button>
                          <button className="capsule-toggle" type="button" onClick={() => void checkSkillUpdate(skill)}>
                            Check
                          </button>
                          <button className="capsule-toggle enabled" type="button" onClick={() => void applySkillUpdate(skill)}>
                            Update
                          </button>
                        </div>
                        );
                      })
                    )}
                  </div>
                </Card.Content>
              </Card>

              <Card className="panel wide-panel compact-panel">
                <Card.Header className="panel-header">
                  <div className="panel-title">
                    <Database size={18} />
                    <span>Credentials</span>
                  </div>
                  <div className="editor-actions">
                    <span>{credentialStatus}</span>
                    <Button size="sm" variant="secondary" onPress={() => void loadCredentials()}>
                      Refresh
                    </Button>
                  </div>
                </Card.Header>
                <Card.Content className="panel-content">
                  <form className="credential-form" onSubmit={submitCredential}>
                    <Input
                      aria-label="Credential id"
                      value={credentialId}
                      onChange={(event) => setCredentialId(event.target.value)}
                    />
                    <Input
                      aria-label="Credential kind"
                      value={credentialKind}
                      onChange={(event) => setCredentialKind(event.target.value)}
                    />
                    <Input
                      aria-label="Credential value"
                      type="password"
                      value={credentialValue}
                      onChange={(event) => setCredentialValue(event.target.value)}
                    />
                    <select
                      className="native-select"
                      aria-label="Credential scope"
                      value={credentialScope}
                      onChange={(event) => setCredentialScope(event.target.value as "global" | "agent")}
                    >
                      <option value="agent">agent</option>
                      <option value="global">global</option>
                    </select>
                    <Button size="sm" variant="primary" type="submit">
                      Save credential
                    </Button>
                  </form>
                  <div className="credential-list">
                    {credentials.length === 0 ? (
                      <p className="empty">No credential references saved. Secret values are never shown again.</p>
                    ) : (
                      credentials.map((credential) => (
                        <article className="credential-row" key={credential.credential_id}>
                          <div>
                            <strong>{credential.credential_id}</strong>
                            <span>
                              {credential.kind} · {credential.scope.level}
                              {credential.scope.agent_id ? `/${credential.scope.agent_id}` : ""}
                            </span>
                          </div>
                          <Button size="sm" variant="secondary" onPress={() => void removeCredential(credential.credential_id)}>
                            Delete
                          </Button>
                        </article>
                      ))
                    )}
                  </div>
                </Card.Content>
              </Card>

              <Card className="panel wide-panel">
                <Card.Header className="panel-header">
                  <div className="panel-title">
                    <Cable size={18} />
                    <span>MCP configuration</span>
                  </div>
                  <div className="editor-actions">
                    <span>{mcpStatus}</span>
                    <Button size="sm" variant="secondary" onPress={addMcpDraft}>
                      Add
                    </Button>
                    <Button size="sm" variant="primary" isDisabled={!mcpDraftsEditable} onPress={() => void saveMcpDrafts()}>
                      Save mcp.json
                    </Button>
                  </div>
                </Card.Header>
                <Card.Content className="panel-content">
                  <div className="mcp-editor">
                    {mcpDrafts.map((draft, index) => (
                      <div className="mcp-row" key={`${draft.name}-${index}`}>
                        <button
                          className={`capsule-toggle ${draft.enabled ? "enabled" : ""}`}
                          type="button"
                          onClick={() => updateMcpDraft(index, { enabled: !draft.enabled })}
                        >
                          {draft.enabled ? "Enabled" : "Disabled"}
                        </button>
                        <Input aria-label="Name" value={draft.name} onChange={(event) => updateMcpDraft(index, { name: event.target.value })} />
                        <select
                          className="native-select"
                          aria-label="Transport"
                          value={draft.transport}
                          onChange={(event) =>
                            updateMcpDraft(index, { transport: event.target.value as McpServerDraft["transport"] })
                          }
                        >
                          <option value="streamable_http">streamable_http</option>
                          <option value="sse">sse</option>
                          <option value="stdio">stdio</option>
                        </select>
                        <Input aria-label="URL" value={draft.url} onChange={(event) => updateMcpDraft(index, { url: event.target.value })} />
                        <Input
                          aria-label="Credential"
                          value={draft.credentialId}
                          onChange={(event) => updateMcpDraft(index, { credentialId: event.target.value })}
                        />
                        <Input
                          aria-label="Command"
                          value={draft.command}
                          onChange={(event) => updateMcpDraft(index, { command: event.target.value })}
                        />
                        <Button size="sm" variant="secondary" onPress={() => removeMcpDraft(index)}>
                          Remove
                        </Button>
                      </div>
                    ))}
                  </div>
                </Card.Content>
              </Card>
            </div>
          </Tabs.Panel>

          <Tabs.Panel id="skills">
            <div className="main-grid configure-grid">
              <Card className="panel wide-panel">
                <Card.Header className="panel-header">
                  <div className="panel-title">
                    <Sparkles size={18} />
                    <span>Skills</span>
                  </div>
                  <div className="editor-actions">
                    <span>{skillSelectionStatus}</span>
                    <Button size="sm" variant="secondary" onPress={() => void saveSkillSelection()}>
                      Save selection
                    </Button>
                  </div>
                </Card.Header>
                <Card.Content className="panel-content">
                  <form className="skill-import" onSubmit={submitSkillInstall}>
                    <div className="inline-actions channel-inputs">
                      <select
                        className="native-select"
                        aria-label="Skill channel"
                        value={skillChannel}
                        onChange={(event) => setSkillChannel(event.target.value as SkillChannel)}
                      >
                        <option value="skills.sh">skills.sh</option>
                        <option value="registry">registry</option>
                        <option value="github">github</option>
                        <option value="local_upload">local_upload</option>
                      </select>
                      {skillChannel === "local_upload" ? (
                        <Input aria-label="Skill directory" value={skillDirectoryName} onChange={(event) => setSkillDirectoryName(event.target.value)} />
                      ) : skillChannel === "github" ? (
                        <>
                          <Input aria-label="GitHub repo" value={skillPackage} onChange={(event) => setSkillPackage(event.target.value)} />
                          <Input aria-label="GitHub ref" value={skillGithubRef} onChange={(event) => setSkillGithubRef(event.target.value)} />
                          <Input aria-label="GitHub skill path" value={skillGithubPath} onChange={(event) => setSkillGithubPath(event.target.value)} />
                          <Input aria-label="Skill name" value={skillName} onChange={(event) => setSkillName(event.target.value)} />
                        </>
                      ) : (
                        <>
                          <Input aria-label="Skill package" value={skillPackage} onChange={(event) => setSkillPackage(event.target.value)} />
                          <Input aria-label="Skill name" value={skillName} onChange={(event) => setSkillName(event.target.value)} />
                        </>
                      )}
                      <Button size="sm" variant="primary" type="submit">
                        {skillChannel === "local_upload" ? "Import" : "Install"}
                      </Button>
                    </div>
                    {skillChannel === "local_upload" ? (
                      <TextArea aria-label="SKILL.md" rows={8} value={skillMarkdown} onChange={(event) => setSkillMarkdown(event.target.value)} />
                    ) : null}
                    <span className="status-line">{skillImportStatus}</span>
                  </form>
                  <div className="skill-list">
                    {skills.length === 0 ? (
                      <p className="empty">Installed skills from the selected workspace appear here.</p>
                    ) : (
                      skills.map((skill) => {
                        const directoryName = skillDirectoryRef(skill);
                        return (
                          <div className="skill-row" key={`skills-tab-${skill.stable_id ?? displayText(skill.path, displayText(skill.name))}`}>
                            <input
                              aria-label={`Select ${displayText(skill.name, skill.stable_id ?? "skill")}`}
                              checked={skillSelection.includes(displayText(skill.name, skill.stable_id ?? ""))}
                              disabled={disabledSkillPaths.includes(skillDisableRef(skill))}
                              type="checkbox"
                              onChange={(event) => toggleSkillSelection(skill, event.target.checked)}
                            />
                            <div>
                              <strong>{displayText(skill.name, skill.stable_id ?? "skill")}</strong>
                              <span>{displayText(skill.path, skill.stable_id ?? "")}</span>
                              {skillUpdateStatus[directoryName] ? <small>{skillUpdateStatus[directoryName]}</small> : null}
                            </div>
                            <button
                              className={`capsule-toggle ${disabledSkillPaths.includes(skillDisableRef(skill)) ? "" : "enabled"}`}
                              type="button"
                              onClick={() => toggleSkillEnabled(skill, disabledSkillPaths.includes(skillDisableRef(skill)))}
                            >
                              {disabledSkillPaths.includes(skillDisableRef(skill)) ? "Disabled" : "Enabled"}
                            </button>
                            <button className="capsule-toggle" type="button" onClick={() => void checkSkillUpdate(skill)}>
                              Check
                            </button>
                            <button className="capsule-toggle enabled" type="button" onClick={() => void applySkillUpdate(skill)}>
                              Update
                            </button>
                          </div>
                        );
                      })
                    )}
                  </div>
                </Card.Content>
              </Card>
            </div>
          </Tabs.Panel>

          <Tabs.Panel id="mcp">
            <Card className="panel wide-panel">
              <Card.Header className="panel-header">
                <div className="panel-title">
                  <Cable size={18} />
                  <span>MCP configuration</span>
                </div>
                <div className="editor-actions">
                  <span>{mcpStatus}</span>
                  <Button size="sm" variant="secondary" onPress={addMcpDraft}>
                    Add
                  </Button>
                  <Button size="sm" variant="primary" isDisabled={!mcpDraftsEditable} onPress={() => void saveMcpDrafts()}>
                    Save mcp.json
                  </Button>
                </div>
              </Card.Header>
              <Card.Content className="panel-content">
                <div className="mcp-editor">
                  {mcpDrafts.map((draft, index) => (
                    <div className="mcp-row" key={`mcp-tab-${draft.name}-${index}`}>
                      <button className={`capsule-toggle ${draft.enabled ? "enabled" : ""}`} type="button" onClick={() => updateMcpDraft(index, { enabled: !draft.enabled })}>
                        {draft.enabled ? "Enabled" : "Disabled"}
                      </button>
                      <Input aria-label="Name" value={draft.name} onChange={(event) => updateMcpDraft(index, { name: event.target.value })} />
                      <select className="native-select" aria-label="Transport" value={draft.transport} onChange={(event) => updateMcpDraft(index, { transport: event.target.value as McpServerDraft["transport"] })}>
                        <option value="streamable_http">streamable_http</option>
                        <option value="sse">sse</option>
                        <option value="stdio">stdio</option>
                      </select>
                      <Input aria-label="URL" value={draft.url} onChange={(event) => updateMcpDraft(index, { url: event.target.value })} />
                      <Input aria-label="Credential" value={draft.credentialId} onChange={(event) => updateMcpDraft(index, { credentialId: event.target.value })} />
                      <Input aria-label="Command" value={draft.command} onChange={(event) => updateMcpDraft(index, { command: event.target.value })} />
                      <Button size="sm" variant="secondary" onPress={() => removeMcpDraft(index)}>
                        Remove
                      </Button>
                    </div>
                  ))}
                </div>
              </Card.Content>
            </Card>
          </Tabs.Panel>

          <Tabs.Panel id="tools">
            <div className="main-grid configure-grid">
              <Card className="panel">
                <Card.Header className="panel-header">
                  <div className="panel-title">
                    <Wrench size={18} />
                    <span>Effective tools</span>
                  </div>
                  <Button size="sm" variant="secondary" onPress={() => void loadToolCatalog()}>
                    Refresh
                  </Button>
                </Card.Header>
                <Card.Content className="panel-content tool-list">
                  {!toolCatalog || toolCatalog.tools.length === 0 ? (
                    <p className="empty">No tools are currently visible to this agent.</p>
                  ) : (
                    toolCatalog.tools.map((tool) => (
                      <article className="tool-row" key={`effective-${tool.name}`}>
                        <div>
                          <strong>{tool.name}</strong>
                          <span>{tool.description || "No description"}</span>
                        </div>
                        <Chip size="sm" variant="soft" color={tool.kind === "command" ? "accent" : "default"}>
                          {tool.kind || tool.reason || "tool"}
                        </Chip>
                      </article>
                    ))
                  )}
                </Card.Content>
              </Card>
              <Card className="panel">
                <Card.Header className="panel-header">
                  <div className="panel-title">
                    <Layers3 size={18} />
                    <span>Available tools</span>
                  </div>
                  <Button size="sm" variant="secondary" onPress={() => void loadAvailableTools()}>
                    Refresh
                  </Button>
                </Card.Header>
                <Card.Content className="panel-content tool-list">
                  {!availableTools || availableTools.tools.length === 0 ? (
                    <p className="empty">No registered tools found.</p>
                  ) : (
                    availableTools.tools.map((tool) => (
                      <article className="tool-row" key={`available-${tool.name}`}>
                        <div>
                          <strong>{tool.name}</strong>
                          <span>{tool.description || "No description"}</span>
                        </div>
                        <button className={`capsule-toggle ${csvToList(agentToolsText).includes(tool.name) ? "enabled" : ""}`} type="button" onClick={() => toggleRequestedTool(tool.name)}>
                          {csvToList(agentToolsText).includes(tool.name) ? "Enabled" : "Disabled"}
                        </button>
                      </article>
                    ))
                  )}
                </Card.Content>
              </Card>
            </div>
          </Tabs.Panel>

          <Tabs.Panel id="files">
            <Card className="panel editor-panel">
              <Card.Header className="panel-header">
                <div className="panel-title">
                  <FileText size={18} />
                  <span>Agent pack source</span>
                </div>
                <div className="editor-actions">
                  <span>{saveStatus}</span>
                  <Button size="sm" variant="secondary" onPress={() => void loadAgentFiles()}>
                    <RefreshCw size={15} />
                    Reload
                  </Button>
                  <Button size="sm" variant="primary" onPress={() => void saveActiveFile()}>
                    Save
                  </Button>
                </div>
              </Card.Header>
              <Card.Content className="panel-content">
                <div className="file-tabs" role="tablist" aria-label="Agent files">
                  {(["agents_md", "agent_yaml", "mcp_json"] as AgentFileKind[]).map((kind) => {
                    const file = fileByKind(agentFiles, kind);
                    return (
                      <button className={activeFileKind === kind ? "active" : ""} type="button" key={`files-${kind}`} onClick={() => switchActiveFile(kind)}>
                        <span>{fileLabels[kind]}</span>
                        <em>{file?.sha256 ? shortHash(file.sha256) : "new"}</em>
                        <i>{enabledFileKinds.includes(kind) ? "Active" : "Disabled"}</i>
                      </button>
                    );
                  })}
                </div>
                <button className={`capsule-toggle file-enable-toggle ${enabledFileKinds.includes(activeFileKind) ? "enabled" : ""}`} type="button" onClick={() => toggleFileKind(activeFileKind)}>
                  {enabledFileKinds.includes(activeFileKind) ? "Active editor" : "Editor disabled"}
                </button>
                <div className="file-path">{fileByKind(agentFiles, activeFileKind)?.path ?? "No file loaded"}</div>
                <TextArea className="source-editor" aria-label={`${fileLabels[activeFileKind]} source`} rows={22} value={editorText} onChange={(event) => setEditorText(event.target.value)} readOnly={!enabledFileKinds.includes(activeFileKind)} />
              </Card.Content>
            </Card>
          </Tabs.Panel>
        </Tabs>
      </section>
    </main>
  );
}
