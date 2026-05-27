import { FormEventHandler } from "react";
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

type ConfigurePageProps = {
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
  skillDirectoryRef: (skill: SkillSummary) => string;
  skillDisableRef: (skill: SkillSummary) => string;
};

export function ConfigurePage({
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
  skillDirectoryRef,
  skillDisableRef,
}: ConfigurePageProps) {
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
