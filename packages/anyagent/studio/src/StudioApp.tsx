import {
  Activity,
  Bot,
  ChevronDown,
  Code2,
  Database,
  FlaskConical,
  Home,
  KeyRound,
  Layers3,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  PackagePlus,
  PlugZap,
  Puzzle,
  Rocket,
  Search,
  Settings,
  Sparkles,
  Sun,
} from "lucide-react";
import { FormEvent, KeyboardEvent as ReactKeyboardEvent, Suspense, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  ChatMessage,
  SkillSummary,
  createAgent,
  getCredentialCapabilities,
  getHealth,
  getStorageHealth,
  getAdminAgent,
  getAgent,
  listAgents,
  listEvents,
  listSkills,
  previewPromptBundle,
  runChat,
  updateAgentConfig,
} from "./anyagentClient";
import { useCredentials } from "./hooks/useCredentials";
import { useAgentFiles } from "./hooks/useAgentFiles";
import { useMcpDrafts } from "./hooks/useMcpDrafts";
import { useObservability } from "./hooks/useObservability";
import { useSkillsManagement } from "./hooks/useSkillsManagement";
import { useToolCatalog } from "./hooks/useToolCatalog";
import { useWorkspaceCatalog } from "./hooks/useWorkspaceCatalog";
import {
  modeForTab,
  navGroupsByMode,
  pathForTab,
  routeToStudioState,
  sectionForTab,
  StudioMode,
  StudioTab,
  subtitleForTab,
  titleForTab,
} from "./navigation";
import { PageErrorBoundary } from "./components/PageErrorBoundary";
import { PageSkeleton } from "./components/PageSkeleton";
import { ToastViewport } from "./components/ToastViewport";
import {
  AgentsPage,
  AuditPage,
  ConfigurePage,
  CredentialsPage,
  DebugPage,
  EvaluationsPage,
  FilesPage,
  HomePage,
  McpPage,
  ObservabilityPage,
  preloadStudioPage,
  PromptsPage,
  SessionsPage,
  SettingsPage,
  SkillsPage,
  ToolsPage,
} from "./pages/lazyPages";
import { useAgentConfigStore } from "./stores/agentConfigStore";
import { StudioConversation, useChatStore } from "./stores/chatStore";
import { useSettingsStore } from "./stores/settingsStore";
import { useToastStore } from "./stores/toastStore";
import { useUiStore } from "./stores/uiStore";
import { normalizeBaseUrl, normalizeSettings } from "./studioSettings";
import {
  csvToList,
  shortHash,
} from "./studioUtils";

export function StudioApp() {
  const location = useLocation();
  const navigate = useNavigate();
  const { mode: studioMode, tab: activeTab } = useMemo(() => routeToStudioState(location.pathname), [location.pathname]);
  const navigateToTab = (tab: StudioTab, mode: StudioMode = modeForTab(tab, studioMode)) => {
    navigate(pathForTab(tab, mode));
  };
  const warmPage = (tab: StudioTab) => {
    preloadStudioPage(tab);
  };
  const { sidebarCollapsed, setSidebarCollapsed, theme, toggleTheme } = useUiStore();
  const showToast = useToastStore((state) => state.showToast);
  const {
    adminStatus,
    applyConnectionDraft,
    connectionDraft,
    connectionTestStatus,
    credentialCapabilities,
    resetStoredSettings,
    serverHealth,
    setAdminHealth,
    setAdminStatus,
    setConnectionTestStatus,
    settings,
    settingsStatus,
    storageHealth,
    updateConnectionDraft,
    updateSettings,
  } = useSettingsStore();
  const {
    activeConversationId,
    activeResponseId,
    conversations,
    input,
    isRunning,
    messages,
    newConversation,
    promptBundle,
    renameConversation,
    replaceMessage,
    selectConversation,
    setActiveResponseId,
    setInput,
    setIsRunning,
    setMessages,
    setPromptBundle,
    setStageEvents,
    setStreamEvents,
    stageEvents,
    streamEvents,
  } = useChatStore();
  const {
    agentConfigStatus,
    agentCreateStatus,
    agentExposed,
    agentModelApiKeyEnv,
    agentModelBaseUrlEnv,
    agentModelDefault,
    agentModelProvider,
    agentSandboxMode,
    agentSpawnText,
    agentToolsText,
    newAgentId,
    newAgentInstructions,
    newAgentTools,
    setAgentConfigStatus,
    setAgentCreateStatus,
    setAgentExposed,
    setAgentModelApiKeyEnv,
    setAgentModelBaseUrlEnv,
    setAgentModelDefault,
    setAgentModelProvider,
    setAgentSandboxMode,
    setAgentSpawnText,
    setAgentToolsText,
    setNewAgentId,
    setNewAgentInstructions,
    setNewAgentTools,
    syncFromAgentDetail,
  } = useAgentConfigStore();
  const { agents, agentDetail, skills, status, refresh } = useWorkspaceCatalog(settings);
  const {
    agentFiles,
    activeFileKind,
    editorText,
    enabledFileKinds,
    saveStatus,
    loadAgentFiles,
    saveActiveFile,
    setAgentFiles,
    setEditorText,
    switchActiveFile,
    toggleFileKind,
  } = useAgentFiles(settings, { onSaved: refresh });
  const {
    disabledSkillPaths,
    setDisabledSkillPaths,
    skillChannel,
    skillDirectoryName,
    skillGithubPath,
    skillGithubRef,
    skillImportStatus,
    skillMarkdown,
    skillName,
    skillPackage,
    skillSelection,
    skillSelectionStatus,
    skillUpdateStatus,
    applySkillUpdate,
    checkSkillUpdate,
    saveSkillSelection,
    setSkillChannel,
    setSkillDirectoryName,
    setSkillGithubPath,
    setSkillGithubRef,
    setSkillMarkdown,
    setSkillName,
    setSkillPackage,
    skillDirectoryRef,
    skillDisableRef,
    submitSkillInstall,
    toggleSkillEnabled,
    toggleSkillSelection,
  } = useSkillsManagement(settings, skills, {
    onFilesRefresh: loadAgentFiles,
    onWorkspaceRefresh: refresh,
  });
  const {
    mcpStatus,
    mcpDrafts,
    mcpDraftsEditable,
    mcpJson,
    addMcpDraft,
    removeMcpDraft,
    saveMcpDrafts,
    updateMcpDraft,
  } = useMcpDrafts(settings, {
    activeFileKind,
    agentFiles,
    onFilesChange: setAgentFiles,
    onEditorTextChange: setEditorText,
    onSaved: refresh,
  });
  const {
    toolCatalog,
    availableTools,
    toolCatalogStatus,
    availableToolsStatus,
    loadToolCatalog,
    loadAvailableTools,
  } = useToolCatalog(settings, agentToolsText);
  const {
    credentials,
    credentialId,
    credentialKind,
    credentialValue,
    credentialScope,
    credentialStatus,
    loadCredentials,
    removeCredential,
    setCredentialId,
    setCredentialKind,
    setCredentialScope,
    setCredentialValue,
    submitCredential,
  } = useCredentials(settings);
  const activeSection = sectionForTab(activeTab);
  const [commandOpen, setCommandOpen] = useState(false);
  const [commandQuery, setCommandQuery] = useState("");

  useEffect(() => {
    preloadStudioPage(activeTab);
  }, [activeTab]);

  useEffect(() => {
    const media = window.matchMedia("(max-width: 860px)");
    const syncSidebar = () => setSidebarCollapsed(media.matches);
    syncSidebar();
    media.addEventListener("change", syncSidebar);
    return () => media.removeEventListener("change", syncSidebar);
  }, [setSidebarCollapsed]);

  useEffect(() => {
    const likelyNext = studioMode === "build" ? ["configure", "skills", "mcp", "tools"] : ["home", "agents", "sessions", "observability"];
    likelyNext.forEach((tab) => preloadStudioPage(tab as StudioTab));
  }, [studioMode]);

  const activeConnection = useMemo(
    () => ({
      baseUrl: normalizeBaseUrl(settings.baseUrl),
      apiKey: settings.apiKey,
      adminKey: settings.adminKey,
    }),
    [settings.adminKey, settings.apiKey, settings.baseUrl],
  );
  const draftConnection = useMemo(
    () => ({
      baseUrl: normalizeBaseUrl(connectionDraft.baseUrl),
      apiKey: connectionDraft.apiKey,
      adminKey: connectionDraft.adminKey,
    }),
    [connectionDraft.adminKey, connectionDraft.apiKey, connectionDraft.baseUrl],
  );
  const hasConnectionDraftChanges = useMemo(
    () =>
      activeConnection.baseUrl !== draftConnection.baseUrl ||
      activeConnection.apiKey !== draftConnection.apiKey ||
      activeConnection.adminKey !== draftConnection.adminKey,
    [activeConnection, draftConnection],
  );
  const selectedSkillCount = useMemo(() => skills.filter((skill) => skill.selected).length, [skills]);
  const {
    displayObservability,
    filteredObservabilityErrors,
    filteredObservabilityTimeline,
    filteredObservabilityTools,
    inspectObservabilityTrace,
    iterationSuggestions,
    observabilityErrors,
    observabilityLimit,
    observabilityMetrics,
    observabilityRuns,
    observabilitySources,
    observabilityStatuses,
    observabilitySummary,
    observabilityTimeline,
    observabilityToolFilter,
    observabilityTools,
    observabilityTrace,
    observabilityTraceId,
    observabilityWindow,
    selectedResponseId,
    selectedRun,
    selectObservabilityRun,
    setObservabilityLimit,
    setObservabilityRefreshNonce,
    setObservabilitySources,
    setObservabilityStatuses,
    setObservabilityToolFilter,
    setObservabilityTraceId,
    setObservabilityWindow,
    setSelectedResponseId,
  } = useObservability(settings, {
    activeResponseId,
    messages,
    selectedSkillCount,
    setActiveResponseId,
    setStageEvents,
    stageEvents,
    streamEvents,
  });
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
  const commandItems = useMemo(() => {
    const pageItems = navGroups
      .flatMap((group) => group.items)
      .map((item) => ({ label: item.label, detail: "Page", tab: item.target, mode: modeForTab(item.target, studioMode) }));
    const agentItems = agents.map((agent) => ({ label: agent.agent_id, detail: "Agent", tab: "agents" as StudioTab, mode: studioMode }));
    const toolItems = (toolCatalog?.tools ?? availableTools?.tools ?? []).map((tool) => ({
      label: tool.name,
      detail: tool.kind || "Tool",
      tab: "tools" as StudioTab,
      mode: "build" as StudioMode,
    }));
    const skillItems = skills.map((skill) => ({
      label: String(skill.name ?? skill.stable_id ?? "skill"),
      detail: "Skill",
      tab: "skills" as StudioTab,
      mode: "build" as StudioMode,
    }));
    const credentialItems = credentials.map((credential) => ({
      label: credential.credential_id,
      detail: credential.kind,
      tab: "credentials" as StudioTab,
      mode: "build" as StudioMode,
    }));
    const needle = commandQuery.trim().toLowerCase();
    return [...pageItems, ...agentItems, ...toolItems, ...skillItems, ...credentialItems]
      .filter((item) => !needle || [item.label, item.detail].some((value) => value.toLowerCase().includes(needle)))
      .slice(0, 12);
  }, [agents, availableTools?.tools, commandQuery, credentials, navGroups, skills, studioMode, toolCatalog?.tools]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setCommandOpen((current) => !current);
      }
      if (event.key === "Escape") {
        setCommandOpen(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  function handleSidebarKeyDown(event: ReactKeyboardEvent<HTMLElement>) {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") {
      return;
    }
    const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>(".nav-item"));
    const currentIndex = buttons.indexOf(document.activeElement as HTMLButtonElement);
    if (currentIndex === -1) {
      return;
    }
    event.preventDefault();
    const offset = event.key === "ArrowDown" ? 1 : -1;
    buttons[(currentIndex + offset + buttons.length) % buttons.length]?.focus();
  }

  async function testConnectionDraft() {
    setConnectionTestStatus("Testing");
    const testSettings = normalizeSettings({ ...settings, ...connectionDraft });
    try {
      const nextAgents = await listAgents(testSettings, true);
      const nextAgentId = testSettings.agentId || nextAgents[0]?.agent_id || "";
      if (nextAgentId) {
        try {
          await getAgent(testSettings, nextAgentId);
        } catch {
          await getAdminAgent(testSettings, nextAgentId);
        }
      }
      setConnectionTestStatus(`Connected${nextAgents.length ? ` · ${nextAgents.length} agents` : ""}`);
      showToast("success", `Connected to ${normalizeBaseUrl(testSettings.baseUrl)}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Connection failed";
      setConnectionTestStatus(message);
      showToast("error", message);
    }
  }

  function applyConnectionWithToast() {
    if (!connectionDraft.baseUrl.trim()) {
      showToast("error", "Server URL is required.");
      return;
    }
    applyConnectionDraft();
    showToast("success", "Connection settings saved.");
  }

  function resetStoredSettingsWithConfirm() {
    if (!window.confirm("Reset browser-local Studio settings?")) {
      return;
    }
    resetStoredSettings();
    showToast("info", "Studio settings reset.");
  }

  useEffect(() => {
    syncFromAgentDetail(agentDetail, settings.model);
  }, [agentDetail, settings.model, syncFromAgentDetail]);

  async function runAssistantTurn(nextMessages: ChatMessage[], assistantMessageId: string) {
    setMessages(nextMessages);
    setIsRunning(true);
    setStreamEvents([]);
    setStageEvents([]);
    setPromptBundle(null);
    setActiveResponseId("");
    setSelectedResponseId("");
    try {
      const result = await runChat(
        settings,
        nextMessages.filter((message) => message.id !== assistantMessageId),
        (delta) => {
          setMessages((current) =>
            current.map((message) =>
              message.id === assistantMessageId ? { ...message, content: message.content + delta } : message,
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
          message.id === assistantMessageId
            ? { ...message, content: error instanceof Error ? error.message : "Request failed" }
            : message,
        ),
      );
    } finally {
      setIsRunning(false);
    }
  }

  async function submitChat(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || isRunning) {
      return;
    }
    const userMessage: ChatMessage = { id: crypto.randomUUID(), role: "user", content: trimmed };
    const assistantMessage: ChatMessage = { id: crypto.randomUUID(), role: "assistant", content: "" };
    setInput("");
    await runAssistantTurn([...messages, userMessage, assistantMessage], assistantMessage.id);
  }

  async function regenerateAssistant(assistantMessageId: string) {
    if (isRunning) {
      return;
    }
    const assistantIndex = messages.findIndex((message) => message.id === assistantMessageId);
    if (assistantIndex < 1) {
      return;
    }
    const previousMessages = messages.slice(0, assistantIndex);
    const userIndex = [...previousMessages].reverse().findIndex((message) => message.role === "user");
    if (userIndex === -1) {
      return;
    }
    const assistantMessage: ChatMessage = { id: crypto.randomUUID(), role: "assistant", content: "" };
    await runAssistantTurn([...previousMessages, assistantMessage], assistantMessage.id);
  }

  async function editUserMessageAndResend(messageId: string, content: string) {
    if (isRunning) {
      return;
    }
    const messageIndex = messages.findIndex((message) => message.id === messageId);
    if (messageIndex === -1 || messages[messageIndex].role !== "user") {
      return;
    }
    const trimmed = content.trim();
    if (!trimmed) {
      return;
    }
    replaceMessage(messageId, trimmed);
    const assistantMessage: ChatMessage = { id: crypto.randomUUID(), role: "assistant", content: "" };
    const nextMessages = [
      ...messages.slice(0, messageIndex),
      { ...messages[messageIndex], content: trimmed },
      assistantMessage,
    ];
    await runAssistantTurn(nextMessages, assistantMessage.id);
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
      if (!/^[a-zA-Z0-9._-]+$/.test(newAgentId.trim())) {
        setAgentCreateStatus("Agent id must use letters, numbers, dot, dash, or underscore");
        showToast("error", "Agent id format is invalid.");
        return;
      }
      if (!newAgentInstructions.trim()) {
        setAgentCreateStatus("Instructions are required");
        showToast("error", "Agent instructions are required.");
        return;
      }
      const created = await createAgent(settings, newAgentId, `${newAgentInstructions.trim()}\n`, requestedToolNames);
      setAgentCreateStatus(`Created ${created.agent.agent_id}`);
      showToast("success", `Created ${created.agent.agent_id}`);
      updateSettings("agentId", created.agent.agent_id);
      await refresh();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Create failed";
      setAgentCreateStatus(message);
      showToast("error", message);
    }
  }

  function toggleRequestedTool(name: string) {
    const current = csvToList(agentToolsText);
    setAgentToolsText(current.includes(name) ? current.filter((item) => item !== name).join(", ") : [...current, name].join(", "));
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
      showToast("success", `Saved ${updated.agent.agent_id}`);
      await refresh();
      await loadToolCatalog();
      await loadAgentFiles();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Save failed";
      setAgentConfigStatus(message);
      showToast("error", message);
    }
  }

  async function loadAdminStatus() {
    setAdminStatus("Loading");
    try {
      const [health, storage, capabilities] = await Promise.all([
        getHealth(settings),
        getStorageHealth(settings),
        getCredentialCapabilities(settings),
      ]);
      setAdminHealth({
        adminStatus: "Ready",
        credentialCapabilities: capabilities,
        serverHealth: health,
        storageHealth: storage,
      });
      showToast("success", "Admin health loaded.");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Admin check failed";
      setAdminHealth({
        adminStatus: message,
        credentialCapabilities: null,
        serverHealth: null,
        storageHealth: null,
      });
      showToast("error", message);
    }
  }

  useEffect(() => {
    void loadAdminStatus();
  }, [settings.baseUrl, settings.apiKey, settings.adminKey]);

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
    <main className={`studio-shell theme-${theme} ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
      <ToastViewport />
      {commandOpen ? (
        <div className="command-backdrop" role="presentation" onMouseDown={() => setCommandOpen(false)}>
          <div className="command-palette" role="dialog" aria-label="Global search" onMouseDown={(event) => event.stopPropagation()}>
            <div className="command-input-row">
              <Search size={17} />
              <input
                autoFocus
                aria-label="Global search"
                placeholder="Search pages, agents, tools, skills, credentials"
                value={commandQuery}
                onChange={(event) => setCommandQuery(event.target.value)}
              />
              <kbd>Esc</kbd>
            </div>
            <div className="command-results">
              {commandItems.length ? (
                commandItems.map((item) => (
                  <button
                    key={`${item.detail}-${item.label}`}
                    type="button"
                    onClick={() => {
                      navigateToTab(item.tab, item.mode);
                      setCommandOpen(false);
                      setCommandQuery("");
                    }}
                  >
                    <strong>{item.label}</strong>
                    <span>{item.detail}</span>
                  </button>
                ))
              ) : (
                <p>No matches</p>
              )}
            </div>
          </div>
        </div>
      ) : null}
      <aside className="sidebar" aria-label="Studio navigation">
        <div className="brand-row">
          <div className="mode-switcher" aria-label="Studio mode">
            <strong>AnyAgent</strong>
            <ChevronDown size={16} />
            <div className="mode-options" role="group" aria-label="Mode switcher">
              <button
                className={studioMode === "use" ? "active" : ""}
                type="button"
                onClick={() => navigateToTab("home", "use")}
                title="Use mode"
              >
                Use
              </button>
              <button
                className={studioMode === "build" ? "active" : ""}
                type="button"
                onClick={() => navigateToTab("configure", "build")}
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

        <nav className="side-nav" aria-label="Primary" onKeyDown={handleSidebarKeyDown}>
          {navGroups.map((group, groupIndex) => (
            <div className="nav-group" key={groupIndex}>
              <span className="nav-group-label">{group.label}</span>
              {group.items.map((item) => (
                <button
                  className={`nav-item ${activeTab === item.target ? "active" : ""}`}
                  type="button"
                  key={item.label}
                  title={item.label}
                  onFocus={() => warmPage(item.target)}
                  onMouseEnter={() => warmPage(item.target)}
                  onClick={() => navigateToTab(item.target, studioMode)}
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
          <button
            className="nav-item"
            type="button"
            onFocus={() => warmPage("settings")}
            onMouseEnter={() => warmPage("settings")}
            onClick={() => navigateToTab("settings", studioMode)}
          >
            <Settings size={16} />
            <span>Settings</span>
          </button>
          <div>
            <strong>{status === "ready" ? "Connected" : "Connection"}</strong>
            <small>{activeConnection.baseUrl}</small>
          </div>
        </div>
      </aside>

      <section className="workspace" role="main" aria-labelledby="studio-page-title">
        <header className="workspace-header">
          <span>{studioMode === "use" ? "Use Mode" : "Build Mode"}</span>
          <button className="theme-toggle" type="button" aria-label="Toggle dark and light theme" onClick={toggleTheme}>
            {theme === "light" ? <Moon size={16} /> : <Sun size={16} />}
          </button>
        </header>

        <div className="project-header">
          <div className="project-icon">
            <Bot size={22} />
          </div>
          <div>
            <h1 id="studio-page-title">{settings.agentId || "Personal"}</h1>
            <p aria-live="polite">ID {settings.agentId || "unselected"} · {status} · {activeConnection.baseUrl}</p>
          </div>
          <div className="project-actions">
            <button
              className="quick-pill"
              type="button"
              onFocus={() => warmPage("settings")}
              onMouseEnter={() => warmPage("settings")}
              onClick={() => navigateToTab("settings", studioMode)}
            >
              <PlugZap size={16} />
              <span>Server</span>
              <strong>{status === "ready" ? "ready" : "check"}</strong>
            </button>
            <button className="quick-pill" type="button">
              <Activity size={16} />
              <span>Traces</span>
              <strong>{streamEvents.length + stageEvents.length}/5000</strong>
            </button>
            <button className="quick-pill" type="button" onFocus={() => warmPage("home")} onMouseEnter={() => warmPage("home")} onClick={() => navigateToTab("home", "use")}>
              <Layers3 size={16} />
              <span>Studio quickstart</span>
            </button>
            <button className="quick-pill" type="button" onFocus={() => warmPage("observability")} onMouseEnter={() => warmPage("observability")} onClick={() => navigateToTab("observability", "use")}>
              <Activity size={16} />
              <span>Tracing quickstart</span>
            </button>
            <button className="quick-pill" type="button" onFocus={() => warmPage("evaluations")} onMouseEnter={() => warmPage("evaluations")} onClick={() => navigateToTab("evaluations", "use")}>
              <Database size={16} />
              <span>Evaluation quickstart</span>
            </button>
          </div>
        </div>

        <div className="page-shell">
          <div className="page-title">
            <span>{titleForTab(activeTab)}</span>
            <small>{subtitleForTab(activeTab, studioMode)}</small>
          </div>

          <PageErrorBoundary title={titleForTab(activeTab)} key={activeTab}>
          <Suspense fallback={<PageSkeleton title={titleForTab(activeTab)} />}>
          {activeTab === "home" ? (
            <HomePage
              mode={studioMode}
              settings={settings}
              agentDetail={agentDetail}
              skillCount={skills.length}
              selectedSkillCount={selectedSkillCount}
              mcpDrafts={mcpDrafts}
              toolCatalog={toolCatalog}
              toolCatalogStatus={toolCatalogStatus}
              agentFiles={agentFiles}
              credentials={credentials}
              availableTools={availableTools}
              adminStatus={adminStatus}
              catalogStatus={status}
              traceRows={traceRows}
              activeConversationId={activeConversationId}
              conversations={conversations}
              messages={messages}
              input={input}
              isRunning={isRunning}
              streamEvents={streamEvents}
              onEditMessage={editUserMessageAndResend}
              onInputChange={setInput}
              onNewConversation={newConversation}
              onRegenerate={regenerateAssistant}
              onRenameConversation={renameConversation}
              onSelectConversation={selectConversation}
              onSubmitChat={submitChat}
              onNavigate={navigateToTab}
            />
          ) : activeTab === "agents" ? (
            <AgentsPage
              mode={studioMode}
              agents={agents}
              settings={settings}
              agentDetail={agentDetail}
              skillCount={skills.length}
              selectedSkillCount={selectedSkillCount}
              toolCatalog={toolCatalog}
              mcpDrafts={mcpDrafts}
              agentCreateStatus={agentCreateStatus}
              newAgentId={newAgentId}
              newAgentTools={newAgentTools}
              newAgentInstructions={newAgentInstructions}
              onSelectAgent={(agentId: string) => updateSettings("agentId", agentId)}
              onRefresh={() => void refresh()}
              onNavigate={navigateToTab}
              onCreateAgent={submitCreateAgent}
              onNewAgentIdChange={setNewAgentId}
              onNewAgentToolsChange={setNewAgentTools}
              onNewAgentInstructionsChange={setNewAgentInstructions}
            />
          ) : activeTab === "sessions" ? (
            <SessionsPage
              settings={settings}
              runs={observabilityRuns}
              selectedRun={selectedRun}
              turnCount={displayObservability.turnCount}
              avgInputChars={displayObservability.avgInputChars}
              onRefresh={() => setObservabilityRefreshNonce((value) => value + 1)}
              onSelectRun={(responseId: string) => void selectObservabilityRun(responseId)}
              onNavigate={navigateToTab}
            />
          ) : activeTab === "evaluations" ? (
            <EvaluationsPage
              agents={agents}
              runs={observabilityRuns}
              settings={settings}
              totalLatency={displayObservability.totalLatency}
              errorCount={observabilityMetrics?.error_count ?? observabilityErrors.length}
              onInspectRun={(responseId: string) => void selectObservabilityRun(responseId)}
              onNavigate={navigateToTab}
            />
          ) : activeTab === "audit" ? (
            <AuditPage
              errors={observabilityErrors}
              runs={observabilityRuns}
              timeline={observabilityTimeline}
              onInspectRun={(responseId: string) => void selectObservabilityRun(responseId)}
              onRefresh={() => setObservabilityRefreshNonce((value) => value + 1)}
            />
          ) : activeTab === "prompts" ? (
            <PromptsPage
              input={input}
              promptBundle={promptBundle}
              agentDetail={agentDetail}
              selectedSkillCount={selectedSkillCount}
              mcpDrafts={mcpDrafts}
              toolCatalog={toolCatalog}
              onInputChange={setInput}
              onPreview={() => void loadPromptPreview()}
            />
          ) : activeTab === "settings" ? (
            <SettingsPage
              mode={studioMode}
              settings={settings}
              connectionDraft={connectionDraft}
              activeConnection={activeConnection}
              hasConnectionDraftChanges={hasConnectionDraftChanges}
              settingsStatus={settingsStatus}
              adminStatus={adminStatus}
              catalogStatus={status}
              connectionTestStatus={connectionTestStatus}
              serverHealth={serverHealth}
              storageHealth={storageHealth}
              credentialCapabilities={credentialCapabilities}
              onConnectionDraftChange={updateConnectionDraft}
              onSettingsChange={updateSettings}
              onTestConnection={() => void testConnectionDraft()}
              onApplyConnection={applyConnectionWithToast}
              onLoadAdminStatus={() => void loadAdminStatus()}
              onReset={resetStoredSettingsWithConfirm}
            />
          ) : activeTab === "credentials" ? (
            <CredentialsPage
              credentials={credentials}
              credentialId={credentialId}
              credentialKind={credentialKind}
              credentialValue={credentialValue}
              credentialScope={credentialScope}
              credentialStatus={credentialStatus}
              onLoadCredentials={() => void loadCredentials()}
              onSubmitCredential={submitCredential}
              onRemoveCredential={(id: string) => {
                if (!window.confirm(`Delete credential reference ${id}?`)) {
                  return;
                }
                void removeCredential(id);
                showToast("info", `Deleted credential ${id}`);
              }}
              onCredentialIdChange={setCredentialId}
              onCredentialKindChange={setCredentialKind}
              onCredentialValueChange={setCredentialValue}
              onCredentialScopeChange={setCredentialScope}
            />
          ) : activeTab === "observability" ? (
            <ObservabilityPage
              settings={settings}
              selectedResponseId={selectedResponseId}
              selectedRun={selectedRun}
              summary={observabilitySummary}
              metrics={observabilityMetrics}
              runs={observabilityRuns}
              tools={observabilityTools}
              errors={observabilityErrors}
              timeline={observabilityTimeline}
              trace={observabilityTrace}
              traceId={observabilityTraceId}
              sources={observabilitySources}
              statuses={observabilityStatuses}
              toolFilter={observabilityToolFilter}
              window={observabilityWindow}
              limit={observabilityLimit}
              display={displayObservability}
              mcpDrafts={mcpDrafts}
              selectedSkillCount={selectedSkillCount}
              filteredTools={filteredObservabilityTools}
              filteredErrors={filteredObservabilityErrors}
              filteredTimeline={filteredObservabilityTimeline}
              iterationSuggestions={iterationSuggestions}
              onWindowChange={setObservabilityWindow}
              onLimitChange={setObservabilityLimit}
              onTraceIdChange={setObservabilityTraceId}
              onSourcesChange={setObservabilitySources}
              onStatusesChange={setObservabilityStatuses}
              onToolFilterChange={setObservabilityToolFilter}
              onRefresh={() => setObservabilityRefreshNonce((value) => value + 1)}
              onSelectRun={(responseId: string) => void selectObservabilityRun(responseId)}
              onInspectTrace={(traceId: string) => void inspectObservabilityTrace(traceId)}
              onNavigate={navigateToTab}
            />
          ) : activeSection === "debug" ? (
            <DebugPage
              stageEvents={stageEvents}
              promptBundle={promptBundle}
              onPreviewPrompt={() => void loadPromptPreview()}
            />
          ) : activeSection === "configure" ? (
            <ConfigurePage
              data={{
                activeBaseUrl: activeConnection.baseUrl,
                activeFileKind,
                agentConfigStatus,
                agentCreateStatus,
                agentDetail,
                agentExposed,
                agentFiles,
                agentId: settings.agentId,
                agentModelApiKeyEnv,
                agentModelBaseUrlEnv,
                agentModelDefault,
                agentModelProvider,
                agentSandboxMode,
                agentSpawnText,
                agentToolsText,
                agents,
                availableTools,
                availableToolsStatus,
                catalogStatus: status,
                connectionDraft,
                connectionTestStatus,
                credentialId,
                credentialKind,
                credentialScope,
                credentialStatus,
                credentialValue,
                credentials,
                disabledSkillPaths,
                editorText,
                enabledFileKinds,
                hasConnectionDraftChanges,
                mcpDrafts,
                mcpDraftsEditable,
                mcpJson,
                mcpStatus,
                model: settings.model,
                newAgentId,
                newAgentInstructions,
                newAgentTools,
                saveStatus,
                sessionKey: settings.sessionKey,
                settingsStatus,
                skillChannel,
                skillDirectoryName,
                skillGithubPath,
                skillGithubRef,
                skillImportStatus,
                skillMarkdown,
                skillName,
                skillPackage,
                skillSelection,
                skillSelectionStatus,
                skillUpdateStatus,
                skills,
                toolCatalog,
                toolCatalogStatus,
              }}
              actions={{
                onActiveFileKindChange: switchActiveFile,
                onAddMcpDraft: addMcpDraft,
                onAgentExposedChange: setAgentExposed,
                onAgentIdChange: (value: string) => updateSettings("agentId", value),
                onAgentModelApiKeyEnvChange: setAgentModelApiKeyEnv,
                onAgentModelBaseUrlEnvChange: setAgentModelBaseUrlEnv,
                onAgentModelDefaultChange: setAgentModelDefault,
                onAgentModelProviderChange: setAgentModelProvider,
                onAgentSandboxModeChange: setAgentSandboxMode,
                onAgentSpawnTextChange: setAgentSpawnText,
                onAgentToolsTextChange: setAgentToolsText,
                onApplyConnection: applyConnectionWithToast,
                onApplySkillUpdate: (skill: SkillSummary) => void applySkillUpdate(skill),
                onCheckSkillUpdate: (skill: SkillSummary) => void checkSkillUpdate(skill),
                onConnectionDraftChange: updateConnectionDraft,
                onCredentialIdChange: setCredentialId,
                onCredentialKindChange: setCredentialKind,
                onCredentialScopeChange: setCredentialScope,
                onCredentialValueChange: setCredentialValue,
                onDisabledSkillPathsChange: setDisabledSkillPaths,
                onEditorTextChange: setEditorText,
                onLoadAgentFiles: () => void loadAgentFiles(),
                onLoadAvailableTools: () => void loadAvailableTools(),
                onLoadCredentials: () => void loadCredentials(),
                onLoadToolCatalog: () => void loadToolCatalog(),
                onModelChange: (value: string) => updateSettings("model", value),
                onNewAgentIdChange: setNewAgentId,
                onNewAgentInstructionsChange: setNewAgentInstructions,
                onNewAgentToolsChange: setNewAgentTools,
                onRefresh: () => void refresh(),
                onRemoveCredential: (id: string) => {
                  if (!window.confirm(`Delete credential reference ${id}?`)) {
                    return;
                  }
                  void removeCredential(id);
                  showToast("info", `Deleted credential ${id}`);
                },
                onRemoveMcpDraft: removeMcpDraft,
                onResetStoredSettings: resetStoredSettingsWithConfirm,
                onSaveActiveFile: () => void saveActiveFile(),
                onSaveAgentConfig: () => void saveAgentConfig(),
                onSaveMcpDrafts: () => void saveMcpDrafts(),
                onSaveSkillSelection: () => void saveSkillSelection(),
                onSessionKeyChange: (value: string) => updateSettings("sessionKey", value),
                onSkillChannelChange: setSkillChannel,
                onSkillDirectoryNameChange: setSkillDirectoryName,
                onSkillGithubPathChange: setSkillGithubPath,
                onSkillGithubRefChange: setSkillGithubRef,
                onSkillMarkdownChange: setSkillMarkdown,
                onSkillNameChange: setSkillName,
                onSkillPackageChange: setSkillPackage,
                onSubmitCreateAgent: submitCreateAgent,
                onSubmitCredential: submitCredential,
                onSubmitSkillInstall: submitSkillInstall,
                onTestConnection: () => void testConnectionDraft(),
                onToggleFileKind: toggleFileKind,
                onToggleRequestedTool: toggleRequestedTool,
                onToggleSkillEnabled: toggleSkillEnabled,
                onToggleSkillSelection: toggleSkillSelection,
                onUpdateMcpDraft: updateMcpDraft,
              }}
              refs={{ skillDirectoryRef, skillDisableRef }}
            />
          ) : activeSection === "skills" ? (
            <SkillsPage
              skills={skills}
              skillChannel={skillChannel}
              skillDirectoryName={skillDirectoryName}
              skillPackage={skillPackage}
              skillGithubRef={skillGithubRef}
              skillGithubPath={skillGithubPath}
              skillName={skillName}
              skillMarkdown={skillMarkdown}
              skillImportStatus={skillImportStatus}
              skillSelection={skillSelection}
              disabledSkillPaths={disabledSkillPaths}
              skillSelectionStatus={skillSelectionStatus}
              skillUpdateStatus={skillUpdateStatus}
              onSubmitSkillInstall={submitSkillInstall}
              onSaveSkillSelection={() => void saveSkillSelection()}
              onSkillChannelChange={setSkillChannel}
              onSkillDirectoryNameChange={setSkillDirectoryName}
              onSkillPackageChange={setSkillPackage}
              onSkillGithubRefChange={setSkillGithubRef}
              onSkillGithubPathChange={setSkillGithubPath}
              onSkillNameChange={setSkillName}
              onSkillMarkdownChange={setSkillMarkdown}
              onToggleSkillSelection={toggleSkillSelection}
              onToggleSkillEnabled={toggleSkillEnabled}
              onCheckSkillUpdate={(skill: SkillSummary) => void checkSkillUpdate(skill)}
              onApplySkillUpdate={(skill: SkillSummary) => void applySkillUpdate(skill)}
              skillDisableRef={skillDisableRef}
              skillDirectoryRef={skillDirectoryRef}
            />
          ) : activeSection === "mcp" ? (
            <McpPage
              drafts={mcpDrafts}
              status={mcpStatus}
              editable={mcpDraftsEditable}
              onAddDraft={addMcpDraft}
              onRemoveDraft={removeMcpDraft}
              onSaveDrafts={() => void saveMcpDrafts()}
              onUpdateDraft={updateMcpDraft}
            />
          ) : activeSection === "tools" ? (
            <ToolsPage
              toolCatalog={toolCatalog}
              availableTools={availableTools}
              requestedToolsText={agentToolsText}
              onLoadToolCatalog={() => void loadToolCatalog()}
              onLoadAvailableTools={() => void loadAvailableTools()}
              onToggleRequestedTool={toggleRequestedTool}
            />
          ) : (
            <FilesPage
              files={agentFiles}
              activeFileKind={activeFileKind}
              enabledFileKinds={enabledFileKinds}
              editorText={editorText}
              saveStatus={saveStatus}
              onActiveFileKindChange={switchActiveFile}
              onEditorTextChange={setEditorText}
              onToggleFileKind={toggleFileKind}
              onReloadFiles={() => void loadAgentFiles()}
              onSaveActiveFile={() => void saveActiveFile()}
            />
          )}
          </Suspense>
          </PageErrorBoundary>
        </div>
      </section>
    </main>
  );
}
