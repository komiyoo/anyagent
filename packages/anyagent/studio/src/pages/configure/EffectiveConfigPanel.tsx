import { Button, Card, Input, TextArea } from "@heroui/react";
import { Braces } from "lucide-react";
import { AgentDetail, ToolCatalog } from "../../anyagentClient";
import { compactJson, csvToList } from "../../studioUtils";
import { ToolCatalogSection } from "./ToolCatalogSection";

type EffectiveConfigPanelProps = {
  agentDetail: AgentDetail | null;
  agentConfigStatus: string;
  agentExposed: boolean;
  agentModelDefault: string;
  agentModelProvider: string;
  agentModelApiKeyEnv: string;
  agentModelBaseUrlEnv: string;
  agentSandboxMode: string;
  agentToolsText: string;
  agentSpawnText: string;
  disabledSkillPaths: string[];
  mcpJson: string;
  toolCatalog: ToolCatalog | null;
  toolCatalogStatus: string;
  availableTools: ToolCatalog | null;
  availableToolsStatus: string;
  onSaveAgentConfig: () => void;
  onAgentExposedChange: (value: boolean) => void;
  onAgentModelDefaultChange: (value: string) => void;
  onAgentModelProviderChange: (value: string) => void;
  onAgentModelApiKeyEnvChange: (value: string) => void;
  onAgentModelBaseUrlEnvChange: (value: string) => void;
  onAgentSandboxModeChange: (value: string) => void;
  onAgentToolsTextChange: (value: string) => void;
  onAgentSpawnTextChange: (value: string) => void;
  onDisabledSkillPathsChange: (value: string[]) => void;
  onLoadToolCatalog: () => void;
  onLoadAvailableTools: () => void;
  onToggleRequestedTool: (name: string) => void;
};

export function EffectiveConfigPanel({
  agentDetail,
  agentConfigStatus,
  agentExposed,
  agentModelDefault,
  agentModelProvider,
  agentModelApiKeyEnv,
  agentModelBaseUrlEnv,
  agentSandboxMode,
  agentToolsText,
  agentSpawnText,
  disabledSkillPaths,
  mcpJson,
  toolCatalog,
  toolCatalogStatus,
  availableTools,
  availableToolsStatus,
  onSaveAgentConfig,
  onAgentExposedChange,
  onAgentModelDefaultChange,
  onAgentModelProviderChange,
  onAgentModelApiKeyEnvChange,
  onAgentModelBaseUrlEnvChange,
  onAgentSandboxModeChange,
  onAgentToolsTextChange,
  onAgentSpawnTextChange,
  onDisabledSkillPathsChange,
  onLoadToolCatalog,
  onLoadAvailableTools,
  onToggleRequestedTool,
}: EffectiveConfigPanelProps) {
  return (
    <Card className="panel">
      <Card.Header className="panel-header">
        <div className="panel-title">
          <Braces size={18} />
          <span>Effective config</span>
        </div>
        <div className="editor-actions">
          <span>{agentConfigStatus}</span>
          <Button size="sm" variant="primary" onPress={onSaveAgentConfig}>
            Save config
          </Button>
        </div>
      </Card.Header>
      <Card.Content className="panel-content">
        <div className="config-form">
          <label className="checkbox-control">
            <input type="checkbox" checked={agentExposed} onChange={(event) => onAgentExposedChange(event.target.checked)} />
            <span>Expose this agent to clients</span>
          </label>
          <label className="control-label">
            <span>Default model</span>
            <Input aria-label="Default model" value={agentModelDefault} onChange={(event) => onAgentModelDefaultChange(event.target.value)} />
          </label>
          <label className="control-label">
            <span>Model provider</span>
            <select
              className="native-select"
              aria-label="Model provider"
              value={agentModelProvider}
              onChange={(event) => onAgentModelProviderChange(event.target.value)}
            >
              <option value="openai">openai</option>
            </select>
          </label>
          <label className="control-label">
            <span>API key env</span>
            <Input aria-label="Model API key env" value={agentModelApiKeyEnv} onChange={(event) => onAgentModelApiKeyEnvChange(event.target.value)} />
          </label>
          <label className="control-label">
            <span>Base URL env</span>
            <Input aria-label="Model base URL env" value={agentModelBaseUrlEnv} onChange={(event) => onAgentModelBaseUrlEnvChange(event.target.value)} />
          </label>
          <label className="control-label">
            <span>Sandbox mode</span>
            <select
              className="native-select"
              aria-label="Sandbox mode"
              value={agentSandboxMode}
              onChange={(event) => onAgentSandboxModeChange(event.target.value)}
            >
              <option value="disabled">disabled</option>
              <option value="opensandbox">opensandbox</option>
              <option value="external">external</option>
              <option value="local-unsafe">local-unsafe</option>
            </select>
          </label>
          <label className="control-label">
            <span>Requested tools</span>
            <Input aria-label="Requested tools" value={agentToolsText} onChange={(event) => onAgentToolsTextChange(event.target.value)} />
          </label>
          <label className="control-label">
            <span>Spawn allow agents</span>
            <Input aria-label="Spawn allow agents" value={agentSpawnText} onChange={(event) => onAgentSpawnTextChange(event.target.value)} />
          </label>
          <label className="control-label">
            <span>Disabled skills</span>
            <Input
              aria-label="Disabled skills"
              value={disabledSkillPaths.join(", ")}
              onChange={(event) => onDisabledSkillPathsChange(csvToList(event.target.value))}
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
                model: agentDetail?.model,
              },
              sandbox_mode: agentDetail?.sandbox?.mode ?? agentDetail?.sandbox_mode,
              requested_tool_names: agentDetail?.tools?.requested_tool_names ?? agentDetail?.requested_tool_names,
              default_selected_skills: agentDetail?.skills?.default_selected ?? agentDetail?.default_selected_skills,
              spawn_allow_agent_ids: agentDetail?.multiagent?.spawn_allow_agent_ids,
            })}
            readOnly
          />
          <TextArea aria-label="mcp.json draft" rows={10} value={mcpJson} readOnly />
        </div>
        <ToolCatalogSection
          toolCatalog={toolCatalog}
          toolCatalogStatus={toolCatalogStatus}
          availableTools={availableTools}
          availableToolsStatus={availableToolsStatus}
          requestedToolsText={agentToolsText}
          onLoadToolCatalog={onLoadToolCatalog}
          onLoadAvailableTools={onLoadAvailableTools}
          onToggleRequestedTool={onToggleRequestedTool}
        />
      </Card.Content>
    </Card>
  );
}
