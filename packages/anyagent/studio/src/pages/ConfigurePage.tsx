import { Button, Card } from "@heroui/react";
import { GitCompareArrows, History, RotateCcw } from "lucide-react";
import { FormEventHandler, useMemo, useState } from "react";
import {
  AgentDetail,
  AgentFileKind,
  AgentSummary,
  AgentWorkspaceFile,
  CredentialRef,
  McpServerDraft,
  SkillChannel,
  SkillSummary,
  ToolCatalog,
} from "../anyagentClient";
import { ConnectionDraft } from "../studioSettings";
import { CredentialsPage } from "./CredentialsPage";
import { FilesPage } from "./FilesPage";
import { McpPage } from "./McpPage";
import { SkillsPage } from "./SkillsPage";
import { ConnectionPanel } from "./configure/ConnectionPanel";
import { CreateAgentPanel } from "./configure/CreateAgentPanel";
import { EffectiveConfigPanel } from "./configure/EffectiveConfigPanel";
import { AgentConfigDraftSnapshot, useConfigVersionStore } from "../stores/configVersionStore";

export type ConfigurePageData = {
  activeBaseUrl: string;
  activeFileKind: AgentFileKind;
  agentConfigStatus: string;
  agentCreateStatus: string;
  agentDetail: AgentDetail | null;
  agentExposed: boolean;
  agentFiles: AgentWorkspaceFile[];
  agentId: string;
  agentModelApiKeyEnv: string;
  agentModelBaseUrlEnv: string;
  agentModelDefault: string;
  agentModelProvider: string;
  agentSandboxMode: string;
  agentSpawnText: string;
  agentToolsText: string;
  agents: AgentSummary[];
  availableTools: ToolCatalog | null;
  availableToolsStatus: string;
  catalogStatus: string;
  connectionDraft: ConnectionDraft;
  connectionTestStatus: string;
  credentialId: string;
  credentialKind: string;
  credentialScope: "global" | "agent";
  credentialStatus: string;
  credentialValue: string;
  credentials: CredentialRef[];
  disabledSkillPaths: string[];
  editorText: string;
  enabledFileKinds: AgentFileKind[];
  hasConnectionDraftChanges: boolean;
  mcpDrafts: McpServerDraft[];
  mcpDraftsEditable: boolean;
  mcpJson: string;
  mcpStatus: string;
  model: string;
  newAgentId: string;
  newAgentInstructions: string;
  newAgentTools: string;
  saveStatus: string;
  sessionKey: string;
  settingsStatus: string;
  skillChannel: SkillChannel;
  skillDirectoryName: string;
  skillGithubPath: string;
  skillGithubRef: string;
  skillImportStatus: string;
  skillMarkdown: string;
  skillName: string;
  skillPackage: string;
  skillSelection: string[];
  skillSelectionStatus: string;
  skillUpdateStatus: Record<string, string>;
  skills: SkillSummary[];
  toolCatalog: ToolCatalog | null;
  toolCatalogStatus: string;
};

export type ConfigurePageActions = {
  onActiveFileKindChange: (kind: AgentFileKind) => void;
  onAddMcpDraft: () => void;
  onAgentExposedChange: (value: boolean) => void;
  onAgentIdChange: (value: string) => void;
  onAgentModelApiKeyEnvChange: (value: string) => void;
  onAgentModelBaseUrlEnvChange: (value: string) => void;
  onAgentModelDefaultChange: (value: string) => void;
  onAgentModelProviderChange: (value: string) => void;
  onAgentSandboxModeChange: (value: string) => void;
  onAgentSpawnTextChange: (value: string) => void;
  onAgentToolsTextChange: (value: string) => void;
  onApplyConnection: () => void;
  onApplySkillUpdate: (skill: SkillSummary) => void;
  onCheckSkillUpdate: (skill: SkillSummary) => void;
  onConnectionDraftChange: <K extends keyof ConnectionDraft>(key: K, value: ConnectionDraft[K]) => void;
  onCredentialIdChange: (value: string) => void;
  onCredentialKindChange: (value: string) => void;
  onCredentialScopeChange: (value: "global" | "agent") => void;
  onCredentialValueChange: (value: string) => void;
  onDisabledSkillPathsChange: (value: string[]) => void;
  onEditorTextChange: (value: string) => void;
  onLoadAgentFiles: () => void;
  onLoadAvailableTools: () => void;
  onLoadCredentials: () => void;
  onLoadToolCatalog: () => void;
  onModelChange: (value: string) => void;
  onNewAgentIdChange: (value: string) => void;
  onNewAgentInstructionsChange: (value: string) => void;
  onNewAgentToolsChange: (value: string) => void;
  onRefresh: () => void;
  onRemoveCredential: (id: string) => void;
  onRemoveMcpDraft: (index: number) => void;
  onResetStoredSettings: () => void;
  onSaveActiveFile: () => void;
  onSaveAgentConfig: () => void;
  onSaveMcpDrafts: () => void;
  onSaveSkillSelection: () => void;
  onSessionKeyChange: (value: string) => void;
  onSkillChannelChange: (value: SkillChannel) => void;
  onSkillDirectoryNameChange: (value: string) => void;
  onSkillGithubPathChange: (value: string) => void;
  onSkillGithubRefChange: (value: string) => void;
  onSkillMarkdownChange: (value: string) => void;
  onSkillNameChange: (value: string) => void;
  onSkillPackageChange: (value: string) => void;
  onSubmitCreateAgent: FormEventHandler<HTMLFormElement>;
  onSubmitCredential: FormEventHandler<HTMLFormElement>;
  onSubmitSkillInstall: FormEventHandler<HTMLFormElement>;
  onTestConnection: () => void;
  onToggleFileKind: (kind: AgentFileKind) => void;
  onToggleRequestedTool: (name: string) => void;
  onToggleSkillEnabled: (skill: SkillSummary, enabled: boolean) => void;
  onToggleSkillSelection: (skill: SkillSummary, checked: boolean) => void;
  onUpdateMcpDraft: (index: number, patch: Partial<McpServerDraft>) => void;
};

export type ConfigurePageRefs = {
  skillDirectoryRef: (skill: SkillSummary) => string;
  skillDisableRef: (skill: SkillSummary) => string;
};

type ConfigurePageProps = {
  actions: ConfigurePageActions;
  data: ConfigurePageData;
  refs: ConfigurePageRefs;
};

export function ConfigurePage({ actions, data, refs }: ConfigurePageProps) {
  const {
  activeBaseUrl,
  activeFileKind,
  agentConfigStatus,
  agentCreateStatus,
  agentDetail,
  agentExposed,
  agentFiles,
  agentId,
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
  catalogStatus,
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
  model,
  newAgentId,
  newAgentInstructions,
  newAgentTools,
  saveStatus,
  sessionKey,
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
  } = data;
  const {
  onActiveFileKindChange,
  onAddMcpDraft,
  onAgentExposedChange,
  onAgentIdChange,
  onAgentModelApiKeyEnvChange,
  onAgentModelBaseUrlEnvChange,
  onAgentModelDefaultChange,
  onAgentModelProviderChange,
  onAgentSandboxModeChange,
  onAgentSpawnTextChange,
  onAgentToolsTextChange,
  onApplyConnection,
  onApplySkillUpdate,
  onCheckSkillUpdate,
  onConnectionDraftChange,
  onCredentialIdChange,
  onCredentialKindChange,
  onCredentialScopeChange,
  onCredentialValueChange,
  onDisabledSkillPathsChange,
  onEditorTextChange,
  onLoadAgentFiles,
  onLoadAvailableTools,
  onLoadCredentials,
  onLoadToolCatalog,
  onModelChange,
  onNewAgentIdChange,
  onNewAgentInstructionsChange,
  onNewAgentToolsChange,
  onRefresh,
  onRemoveCredential,
  onRemoveMcpDraft,
  onResetStoredSettings,
  onSaveActiveFile,
  onSaveAgentConfig,
  onSaveMcpDrafts,
  onSaveSkillSelection,
  onSessionKeyChange,
  onSkillChannelChange,
  onSkillDirectoryNameChange,
  onSkillGithubPathChange,
  onSkillGithubRefChange,
  onSkillMarkdownChange,
  onSkillNameChange,
  onSkillPackageChange,
  onSubmitCreateAgent,
  onSubmitCredential,
  onSubmitSkillInstall,
  onTestConnection,
  onToggleFileKind,
  onToggleRequestedTool,
  onToggleSkillEnabled,
  onToggleSkillSelection,
  onUpdateMcpDraft,
  } = actions;
  const {
  skillDirectoryRef,
  skillDisableRef,
  } = refs;
  const [leftAgentId, setLeftAgentId] = useState(agentId);
  const [rightAgentId, setRightAgentId] = useState(agents.find((agent) => agent.agent_id !== agentId)?.agent_id ?? agentId);
  const { addSnapshot, removeSnapshot, snapshots } = useConfigVersionStore();
  const currentConfig: AgentConfigDraftSnapshot = useMemo(
    () => ({
      agentId,
      disabledSkillPaths,
      exposed: agentExposed,
      mcpJson,
      modelApiKeyEnv: agentModelApiKeyEnv,
      modelBaseUrlEnv: agentModelBaseUrlEnv,
      modelDefault: agentModelDefault,
      modelProvider: agentModelProvider,
      sandboxMode: agentSandboxMode,
      spawnText: agentSpawnText,
      toolsText: agentToolsText,
    }),
    [
      agentId,
      agentExposed,
      agentModelApiKeyEnv,
      agentModelBaseUrlEnv,
      agentModelDefault,
      agentModelProvider,
      agentSandboxMode,
      agentSpawnText,
      agentToolsText,
      disabledSkillPaths,
      mcpJson,
    ],
  );
  const agentSnapshots = snapshots.filter((snapshot) => snapshot.agentId === agentId);
  const baseline = agentSnapshots[0]?.config;
  const configDiff = Object.entries(currentConfig).filter(([key, value]) => {
    const previous = baseline?.[key as keyof AgentConfigDraftSnapshot];
    return JSON.stringify(previous ?? "") !== JSON.stringify(value ?? "");
  });
  const leftAgent = agents.find((agent) => agent.agent_id === leftAgentId);
  const rightAgent = agents.find((agent) => agent.agent_id === rightAgentId);
  const compareRows = [
    ["Exposed", String(leftAgent?.exposed ?? "-"), String(rightAgent?.exposed ?? "-")],
    ["Model", leftAgent?.model_default ?? "-", rightAgent?.model_default ?? "-"],
    ["Provider", leftAgent?.model_provider ?? "-", rightAgent?.model_provider ?? "-"],
    ["Sandbox", leftAgent?.sandbox_mode ?? "-", rightAgent?.sandbox_mode ?? "-"],
    ["Requested tools", String(leftAgent?.requested_tool_names?.length ?? 0), String(rightAgent?.requested_tool_names?.length ?? 0)],
    ["Default skills", String(leftAgent?.default_selected_skills?.length ?? 0), String(rightAgent?.default_selected_skills?.length ?? 0)],
  ];

  function rollbackConfig(snapshot: AgentConfigDraftSnapshot) {
    onAgentExposedChange(snapshot.exposed);
    onAgentModelDefaultChange(snapshot.modelDefault);
    onModelChange(snapshot.modelDefault);
    onAgentModelProviderChange(snapshot.modelProvider);
    onAgentModelApiKeyEnvChange(snapshot.modelApiKeyEnv);
    onAgentModelBaseUrlEnvChange(snapshot.modelBaseUrlEnv);
    onAgentSandboxModeChange(snapshot.sandboxMode);
    onAgentToolsTextChange(snapshot.toolsText);
    onAgentSpawnTextChange(snapshot.spawnText);
    onDisabledSkillPathsChange(snapshot.disabledSkillPaths);
  }

  return (
    <div className="main-grid configure-grid">
      <ConnectionPanel
        activeBaseUrl={activeBaseUrl}
        catalogStatus={catalogStatus}
        connectionDraft={connectionDraft}
        connectionTestStatus={connectionTestStatus}
        settingsStatus={settingsStatus}
        hasDraftChanges={hasConnectionDraftChanges}
        model={model}
        agentId={agentId}
        sessionKey={sessionKey}
        agents={agents}
        onConnectionDraftChange={onConnectionDraftChange}
        onModelChange={onModelChange}
        onAgentIdChange={onAgentIdChange}
        onSessionKeyChange={onSessionKeyChange}
        onTestConnection={onTestConnection}
        onApplyConnection={onApplyConnection}
        onRefresh={onRefresh}
        onResetStoredSettings={onResetStoredSettings}
      />

      <CreateAgentPanel
        agentCreateStatus={agentCreateStatus}
        newAgentId={newAgentId}
        newAgentTools={newAgentTools}
        newAgentInstructions={newAgentInstructions}
        onSubmit={onSubmitCreateAgent}
        onNewAgentIdChange={onNewAgentIdChange}
        onNewAgentToolsChange={onNewAgentToolsChange}
        onNewAgentInstructionsChange={onNewAgentInstructionsChange}
      />

      <FilesPage
        files={agentFiles}
        activeFileKind={activeFileKind}
        enabledFileKinds={enabledFileKinds}
        editorText={editorText}
        saveStatus={saveStatus}
        onActiveFileKindChange={onActiveFileKindChange}
        onEditorTextChange={onEditorTextChange}
        onToggleFileKind={onToggleFileKind}
        onReloadFiles={onLoadAgentFiles}
        onSaveActiveFile={onSaveActiveFile}
      />

      <EffectiveConfigPanel
        agentDetail={agentDetail}
        agentConfigStatus={agentConfigStatus}
        agentExposed={agentExposed}
        agentModelDefault={agentModelDefault}
        agentModelProvider={agentModelProvider}
        agentModelApiKeyEnv={agentModelApiKeyEnv}
        agentModelBaseUrlEnv={agentModelBaseUrlEnv}
        agentSandboxMode={agentSandboxMode}
        agentToolsText={agentToolsText}
        agentSpawnText={agentSpawnText}
        disabledSkillPaths={disabledSkillPaths}
        mcpJson={mcpJson}
        toolCatalog={toolCatalog}
        toolCatalogStatus={toolCatalogStatus}
        availableTools={availableTools}
        availableToolsStatus={availableToolsStatus}
        onSaveAgentConfig={onSaveAgentConfig}
        onAgentExposedChange={onAgentExposedChange}
        onAgentModelDefaultChange={(value) => {
          onAgentModelDefaultChange(value);
          onModelChange(value);
        }}
        onAgentModelProviderChange={onAgentModelProviderChange}
        onAgentModelApiKeyEnvChange={onAgentModelApiKeyEnvChange}
        onAgentModelBaseUrlEnvChange={onAgentModelBaseUrlEnvChange}
        onAgentSandboxModeChange={onAgentSandboxModeChange}
        onAgentToolsTextChange={onAgentToolsTextChange}
        onAgentSpawnTextChange={onAgentSpawnTextChange}
        onDisabledSkillPathsChange={onDisabledSkillPathsChange}
        onLoadToolCatalog={onLoadToolCatalog}
        onLoadAvailableTools={onLoadAvailableTools}
        onToggleRequestedTool={onToggleRequestedTool}
      />

      <Card className="panel wide-panel">
        <Card.Header className="panel-header">
          <div className="panel-title">
            <History size={18} />
            <span>Config versions</span>
          </div>
          <Button size="sm" variant="secondary" onPress={() => addSnapshot(agentId, currentConfig)}>
            Save snapshot
          </Button>
        </Card.Header>
        <Card.Content className="panel-content">
          <div className="version-grid">
            <section className="version-column">
              <div className="subsection-heading">
                <span>Diff from latest snapshot</span>
              </div>
              <div className="breakdown-list">
                {baseline ? (
                  configDiff.length ? (
                    configDiff.map(([key, value]) => (
                      <div className="breakdown-row" key={key}>
                        <span>{key}</span>
                        <strong>{Array.isArray(value) ? value.join(", ") : String(value || "-")}</strong>
                      </div>
                    ))
                  ) : (
                    <div className="breakdown-row">
                      <span>No changes</span>
                      <strong>clean</strong>
                    </div>
                  )
                ) : (
                  <div className="breakdown-row">
                    <span>No baseline</span>
                    <strong>save a snapshot</strong>
                  </div>
                )}
              </div>
            </section>
            <section className="version-column">
              <div className="subsection-heading">
                <span>Snapshots</span>
              </div>
              <div className="snapshot-list">
                {agentSnapshots.length ? (
                  agentSnapshots.map((snapshot) => (
                    <article className="snapshot-row" key={snapshot.id}>
                      <div>
                        <strong>{snapshot.name}</strong>
                        <span>{new Date(snapshot.createdAt).toLocaleString()}</span>
                      </div>
                      <Button size="sm" variant="ghost" isIconOnly aria-label="Rollback snapshot" onPress={() => rollbackConfig(snapshot.config)}>
                        <RotateCcw size={15} />
                      </Button>
                      <Button size="sm" variant="ghost" onPress={() => removeSnapshot(snapshot.id)}>
                        Remove
                      </Button>
                    </article>
                  ))
                ) : (
                  <p className="empty">Saved snapshots for the current agent appear here.</p>
                )}
              </div>
            </section>
          </div>
        </Card.Content>
      </Card>

      <Card className="panel wide-panel">
        <Card.Header className="panel-header">
          <div className="panel-title">
            <GitCompareArrows size={18} />
            <span>Agent compare</span>
          </div>
        </Card.Header>
        <Card.Content className="panel-content">
          <div className="filter-row">
            <select className="native-select" aria-label="Left agent" value={leftAgentId} onChange={(event) => setLeftAgentId(event.target.value)}>
              {agents.map((agent) => (
                <option key={`left-${agent.agent_id}`} value={agent.agent_id}>
                  {agent.agent_id}
                </option>
              ))}
            </select>
            <select className="native-select" aria-label="Right agent" value={rightAgentId} onChange={(event) => setRightAgentId(event.target.value)}>
              {agents.map((agent) => (
                <option key={`right-${agent.agent_id}`} value={agent.agent_id}>
                  {agent.agent_id}
                </option>
              ))}
            </select>
          </div>
          <div className="compare-table">
            {compareRows.map(([label, left, right]) => (
              <div className={left === right ? "" : "changed"} key={label}>
                <span>{label}</span>
                <strong>{left}</strong>
                <strong>{right}</strong>
              </div>
            ))}
          </div>
        </Card.Content>
      </Card>

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
        onSubmitSkillInstall={onSubmitSkillInstall}
        onSaveSkillSelection={onSaveSkillSelection}
        onSkillChannelChange={onSkillChannelChange}
        onSkillDirectoryNameChange={onSkillDirectoryNameChange}
        onSkillPackageChange={onSkillPackageChange}
        onSkillGithubRefChange={onSkillGithubRefChange}
        onSkillGithubPathChange={onSkillGithubPathChange}
        onSkillNameChange={onSkillNameChange}
        onSkillMarkdownChange={onSkillMarkdownChange}
        onToggleSkillSelection={onToggleSkillSelection}
        onToggleSkillEnabled={onToggleSkillEnabled}
        onCheckSkillUpdate={onCheckSkillUpdate}
        onApplySkillUpdate={onApplySkillUpdate}
        skillDisableRef={skillDisableRef}
        skillDirectoryRef={skillDirectoryRef}
      />

      <CredentialsPage
        credentials={credentials}
        credentialId={credentialId}
        credentialKind={credentialKind}
        credentialValue={credentialValue}
        credentialScope={credentialScope}
        credentialStatus={credentialStatus}
        onLoadCredentials={onLoadCredentials}
        onSubmitCredential={onSubmitCredential}
        onRemoveCredential={onRemoveCredential}
        onCredentialIdChange={onCredentialIdChange}
        onCredentialKindChange={onCredentialKindChange}
        onCredentialValueChange={onCredentialValueChange}
        onCredentialScopeChange={onCredentialScopeChange}
      />

      <McpPage
        drafts={mcpDrafts}
        status={mcpStatus}
        editable={mcpDraftsEditable}
        onAddDraft={onAddMcpDraft}
        onRemoveDraft={onRemoveMcpDraft}
        onSaveDrafts={onSaveMcpDrafts}
        onUpdateDraft={onUpdateMcpDraft}
      />
    </div>
  );
}
