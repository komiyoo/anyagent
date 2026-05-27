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
  PanelLeftClose,
  PanelLeftOpen,
  PackagePlus,
  PlugZap,
  Puzzle,
  Rocket,
  Search,
  Settings,
  Sparkles,
} from "lucide-react";
import { FormEvent, lazy, Suspense, useEffect, useMemo, useState } from "react";
import {
  AgentDetail,
  ChatMessage,
  AdminStatus,
  StudioDebugEvent,
  StudioSettings,
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
import { navGroupsByMode, sectionForTab, StudioMode, StudioTab, subtitleForTab, titleForTab } from "./navigation";
import { clearStoredSettings, ConnectionDraft, envSettings, normalizeBaseUrl, normalizeSettings, readStoredSettings, writeStoredSettings } from "./studioSettings";
import {
  csvToList,
  shortHash,
} from "./studioUtils";

const AgentsPage = lazy(() => import("./pages/AgentsPage").then((module) => ({ default: module.AgentsPage })));
const ConfigurePage = lazy(() => import("./pages/ConfigurePage").then((module) => ({ default: module.ConfigurePage })));
const CredentialsPage = lazy(() => import("./pages/CredentialsPage").then((module) => ({ default: module.CredentialsPage })));
const DebugPage = lazy(() => import("./pages/DebugPage").then((module) => ({ default: module.DebugPage })));
const EvaluationsPage = lazy(() => import("./pages/EvaluationsPage").then((module) => ({ default: module.EvaluationsPage })));
const FilesPage = lazy(() => import("./pages/FilesPage").then((module) => ({ default: module.FilesPage })));
const HomePage = lazy(() => import("./pages/HomePage").then((module) => ({ default: module.HomePage })));
const McpPage = lazy(() => import("./pages/McpPage").then((module) => ({ default: module.McpPage })));
const ObservabilityPage = lazy(() => import("./pages/ObservabilityPage").then((module) => ({ default: module.ObservabilityPage })));
const PromptsPage = lazy(() => import("./pages/PromptsPage").then((module) => ({ default: module.PromptsPage })));
const SessionsPage = lazy(() => import("./pages/SessionsPage").then((module) => ({ default: module.SessionsPage })));
const SettingsPage = lazy(() => import("./pages/SettingsPage").then((module) => ({ default: module.SettingsPage })));
const SkillsPage = lazy(() => import("./pages/SkillsPage").then((module) => ({ default: module.SkillsPage })));
const ToolsPage = lazy(() => import("./pages/ToolsPage").then((module) => ({ default: module.ToolsPage })));

export function StudioApp() {
  const [settings, setSettings] = useState<StudioSettings>(() => readStoredSettings());
  const [connectionDraft, setConnectionDraft] = useState<ConnectionDraft>(() => {
    const initial = readStoredSettings();
    return { baseUrl: initial.baseUrl, apiKey: initial.apiKey, adminKey: initial.adminKey };
  });
  const [settingsStatus, setSettingsStatus] = useState("Loaded");
  const [connectionTestStatus, setConnectionTestStatus] = useState("Not tested");
  const [studioMode, setStudioMode] = useState<StudioMode>("use");
  const [activeTab, setActiveTab] = useState<StudioTab>("home");
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
  const [streamEvents, setStreamEvents] = useState<StudioDebugEvent[]>([]);
  const [stageEvents, setStageEvents] = useState<StudioDebugEvent[]>([]);
  const [promptBundle, setPromptBundle] = useState<Record<string, unknown> | null>(null);
  const [newAgentId, setNewAgentId] = useState("sales-agent");
  const [newAgentTools, setNewAgentTools] = useState("");
  const [newAgentInstructions, setNewAgentInstructions] = useState("你是一个面向业务团队的 AnyAgent agent。");
  const [agentCreateStatus, setAgentCreateStatus] = useState("Ready");
  const [agentExposed, setAgentExposed] = useState(true);
  const [agentModelDefault, setAgentModelDefault] = useState("");
  const [agentModelProvider, setAgentModelProvider] = useState("openai");
  const [agentModelBaseUrlEnv, setAgentModelBaseUrlEnv] = useState("OPENAI_BASE_URL");
  const [agentModelApiKeyEnv, setAgentModelApiKeyEnv] = useState("OPENAI_API_KEY");
  const [agentSandboxMode, setAgentSandboxMode] = useState("disabled");
  const [agentToolsText, setAgentToolsText] = useState("");
  const [agentSpawnText, setAgentSpawnText] = useState("");
  const [agentConfigStatus, setAgentConfigStatus] = useState("Ready");
  const [serverHealth, setServerHealth] = useState<AdminStatus | null>(null);
  const [storageHealth, setStorageHealth] = useState<AdminStatus | null>(null);
  const [credentialCapabilities, setCredentialCapabilities] = useState<AdminStatus | null>(null);
  const [adminStatus, setAdminStatus] = useState("Not loaded");
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
    observabilitySource,
    observabilityStatus,
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
    setObservabilitySource,
    setObservabilityStatus,
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

  function updateSettings<K extends keyof StudioSettings>(key: K, value: StudioSettings[K]) {
    setSettings((previous) => {
      const next = normalizeSettings({ ...previous, [key]: value });
      writeStoredSettings(next);
      setSettingsStatus("Saved");
      return next;
    });
  }

  function updateConnectionDraft<K extends keyof ConnectionDraft>(key: K, value: ConnectionDraft[K]) {
    setConnectionDraft((previous) => ({ ...previous, [key]: value }));
    setConnectionTestStatus("Not tested");
    setSettingsStatus("Unsaved connection changes");
  }

  function applyConnectionDraft() {
    setSettings((previous) => {
      const next = normalizeSettings({ ...previous, ...connectionDraft });
      writeStoredSettings(next);
      setConnectionDraft({ baseUrl: next.baseUrl, apiKey: next.apiKey, adminKey: next.adminKey });
      setSettingsStatus("Connection applied and saved");
      return next;
    });
  }

  function resetStoredSettings() {
    clearStoredSettings();
    const next = normalizeSettings(envSettings);
    setSettings(next);
    setConnectionDraft({ baseUrl: next.baseUrl, apiKey: next.apiKey, adminKey: next.adminKey });
    setSettingsStatus("Reset to environment defaults");
    setConnectionTestStatus("Not tested");
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
    } catch (error) {
      setConnectionTestStatus(error instanceof Error ? error.message : "Connection failed");
    }
  }

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
      await refresh();
      await loadToolCatalog();
      await loadAgentFiles();
    } catch (error) {
      setAgentConfigStatus(error instanceof Error ? error.message : "Save failed");
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
      setServerHealth(health);
      setStorageHealth(storage);
      setCredentialCapabilities(capabilities);
      setAdminStatus("Ready");
    } catch (error) {
      setServerHealth(null);
      setStorageHealth(null);
      setCredentialCapabilities(null);
      setAdminStatus(error instanceof Error ? error.message : "Admin check failed");
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
                  setActiveTab("home");
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
          <button className="nav-item" type="button" onClick={() => setActiveTab("settings")}>
            <Settings size={16} />
            <span>Settings</span>
          </button>
          <div>
            <strong>{status === "ready" ? "Connected" : "Connection"}</strong>
            <small>{activeConnection.baseUrl}</small>
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
            <p>ID {settings.agentId || "unselected"} · {status} · {activeConnection.baseUrl}</p>
          </div>
          <div className="project-actions">
            <button className="quick-pill" type="button" onClick={() => setActiveTab("settings")}>
              <PlugZap size={16} />
              <span>Server</span>
              <strong>{status === "ready" ? "ready" : "check"}</strong>
            </button>
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

        <div className="page-shell">
          <div className="page-title">
            <span>{titleForTab(activeTab)}</span>
            <small>{subtitleForTab(activeTab, studioMode)}</small>
          </div>

          <Suspense fallback={<div className="page-loading">Loading page</div>}>
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
              traceRows={traceRows}
              messages={messages}
              input={input}
              isRunning={isRunning}
              streamEvents={streamEvents}
              onInputChange={setInput}
              onSubmitChat={submitChat}
              onNavigate={setActiveTab}
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
              onSelectAgent={(agentId) => updateSettings("agentId", agentId)}
              onRefresh={() => void refresh()}
              onNavigate={setActiveTab}
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
              onSelectRun={(responseId) => void selectObservabilityRun(responseId)}
            />
          ) : activeTab === "evaluations" ? (
            <EvaluationsPage
              runs={observabilityRuns}
              totalLatency={displayObservability.totalLatency}
              errorCount={observabilityMetrics?.error_count ?? observabilityErrors.length}
              onInspectRun={(responseId) => void selectObservabilityRun(responseId)}
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
              onApplyConnection={applyConnectionDraft}
              onLoadAdminStatus={() => void loadAdminStatus()}
              onReset={resetStoredSettings}
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
              onRemoveCredential={(id) => void removeCredential(id)}
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
              source={observabilitySource}
              status={observabilityStatus}
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
              onSourceChange={setObservabilitySource}
              onStatusChange={setObservabilityStatus}
              onToolFilterChange={setObservabilityToolFilter}
              onRefresh={() => setObservabilityRefreshNonce((value) => value + 1)}
              onSelectRun={(responseId) => void selectObservabilityRun(responseId)}
              onInspectTrace={(traceId) => void inspectObservabilityTrace(traceId)}
              onNavigate={setActiveTab}
            />
          ) : activeSection === "debug" ? (
            <DebugPage
              stageEvents={stageEvents}
              promptBundle={promptBundle}
              onPreviewPrompt={() => void loadPromptPreview()}
            />
          ) : activeSection === "configure" ? (
            <ConfigurePage
              activeBaseUrl={activeConnection.baseUrl}
              activeFileKind={activeFileKind}
              agentConfigStatus={agentConfigStatus}
              agentCreateStatus={agentCreateStatus}
              agentDetail={agentDetail}
              agentExposed={agentExposed}
              agentFiles={agentFiles}
              agentId={settings.agentId}
              agentModelApiKeyEnv={agentModelApiKeyEnv}
              agentModelBaseUrlEnv={agentModelBaseUrlEnv}
              agentModelDefault={agentModelDefault}
              agentModelProvider={agentModelProvider}
              agentSandboxMode={agentSandboxMode}
              agentSpawnText={agentSpawnText}
              agentToolsText={agentToolsText}
              agents={agents}
              availableTools={availableTools}
              availableToolsStatus={availableToolsStatus}
              catalogStatus={status}
              connectionDraft={connectionDraft}
              connectionTestStatus={connectionTestStatus}
              credentials={credentials}
              credentialId={credentialId}
              credentialKind={credentialKind}
              credentialValue={credentialValue}
              credentialScope={credentialScope}
              credentialStatus={credentialStatus}
              disabledSkillPaths={disabledSkillPaths}
              editorText={editorText}
              enabledFileKinds={enabledFileKinds}
              hasConnectionDraftChanges={hasConnectionDraftChanges}
              mcpDrafts={mcpDrafts}
              mcpDraftsEditable={mcpDraftsEditable}
              mcpJson={mcpJson}
              mcpStatus={mcpStatus}
              model={settings.model}
              newAgentId={newAgentId}
              newAgentInstructions={newAgentInstructions}
              newAgentTools={newAgentTools}
              saveStatus={saveStatus}
              sessionKey={settings.sessionKey}
              settingsStatus={settingsStatus}
              skillChannel={skillChannel}
              skillDirectoryName={skillDirectoryName}
              skillGithubPath={skillGithubPath}
              skillGithubRef={skillGithubRef}
              skillImportStatus={skillImportStatus}
              skillMarkdown={skillMarkdown}
              skillName={skillName}
              skillPackage={skillPackage}
              skillSelection={skillSelection}
              skillSelectionStatus={skillSelectionStatus}
              skillUpdateStatus={skillUpdateStatus}
              skills={skills}
              toolCatalog={toolCatalog}
              toolCatalogStatus={toolCatalogStatus}
              onActiveFileKindChange={switchActiveFile}
              onAddMcpDraft={addMcpDraft}
              onAgentExposedChange={setAgentExposed}
              onAgentIdChange={(value) => updateSettings("agentId", value)}
              onAgentModelApiKeyEnvChange={setAgentModelApiKeyEnv}
              onAgentModelBaseUrlEnvChange={setAgentModelBaseUrlEnv}
              onAgentModelDefaultChange={setAgentModelDefault}
              onAgentModelProviderChange={setAgentModelProvider}
              onAgentSandboxModeChange={setAgentSandboxMode}
              onAgentSpawnTextChange={setAgentSpawnText}
              onAgentToolsTextChange={setAgentToolsText}
              onApplyConnection={applyConnectionDraft}
              onApplySkillUpdate={(skill) => void applySkillUpdate(skill)}
              onCheckSkillUpdate={(skill) => void checkSkillUpdate(skill)}
              onConnectionDraftChange={updateConnectionDraft}
              onCredentialIdChange={setCredentialId}
              onCredentialKindChange={setCredentialKind}
              onCredentialScopeChange={setCredentialScope}
              onCredentialValueChange={setCredentialValue}
              onDisabledSkillPathsChange={setDisabledSkillPaths}
              onEditorTextChange={setEditorText}
              onLoadAgentFiles={() => void loadAgentFiles()}
              onLoadAvailableTools={() => void loadAvailableTools()}
              onLoadCredentials={() => void loadCredentials()}
              onLoadToolCatalog={() => void loadToolCatalog()}
              onModelChange={(value) => updateSettings("model", value)}
              onNewAgentIdChange={setNewAgentId}
              onNewAgentInstructionsChange={setNewAgentInstructions}
              onNewAgentToolsChange={setNewAgentTools}
              onRefresh={() => void refresh()}
              onRemoveCredential={(id) => void removeCredential(id)}
              onRemoveMcpDraft={removeMcpDraft}
              onResetStoredSettings={resetStoredSettings}
              onSaveActiveFile={() => void saveActiveFile()}
              onSaveAgentConfig={() => void saveAgentConfig()}
              onSaveMcpDrafts={() => void saveMcpDrafts()}
              onSaveSkillSelection={() => void saveSkillSelection()}
              onSessionKeyChange={(value) => updateSettings("sessionKey", value)}
              onSkillChannelChange={setSkillChannel}
              onSkillDirectoryNameChange={setSkillDirectoryName}
              onSkillGithubPathChange={setSkillGithubPath}
              onSkillGithubRefChange={setSkillGithubRef}
              onSkillMarkdownChange={setSkillMarkdown}
              onSkillNameChange={setSkillName}
              onSkillPackageChange={setSkillPackage}
              onSubmitCreateAgent={submitCreateAgent}
              onSubmitCredential={submitCredential}
              onSubmitSkillInstall={submitSkillInstall}
              onTestConnection={() => void testConnectionDraft()}
              onToggleFileKind={toggleFileKind}
              onToggleRequestedTool={toggleRequestedTool}
              onToggleSkillEnabled={toggleSkillEnabled}
              onToggleSkillSelection={toggleSkillSelection}
              onUpdateMcpDraft={updateMcpDraft}
              skillDirectoryRef={skillDirectoryRef}
              skillDisableRef={skillDisableRef}
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
              onCheckSkillUpdate={(skill) => void checkSkillUpdate(skill)}
              onApplySkillUpdate={(skill) => void applySkillUpdate(skill)}
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
        </div>
      </section>
    </main>
  );
}
