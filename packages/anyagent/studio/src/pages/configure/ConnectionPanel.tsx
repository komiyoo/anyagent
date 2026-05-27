import { Button, Card, Input } from "@heroui/react";
import { Cable, PlugZap, RefreshCw, Settings } from "lucide-react";
import { AgentSummary } from "../../anyagentClient";
import { ConnectionDraft } from "../../studioSettings";

type ConnectionPanelProps = {
  activeBaseUrl: string;
  catalogStatus: string;
  connectionDraft: ConnectionDraft;
  connectionTestStatus: string;
  settingsStatus: string;
  hasDraftChanges: boolean;
  model: string;
  agentId: string;
  sessionKey: string;
  agents: AgentSummary[];
  onConnectionDraftChange: <K extends keyof ConnectionDraft>(key: K, value: ConnectionDraft[K]) => void;
  onModelChange: (value: string) => void;
  onAgentIdChange: (value: string) => void;
  onSessionKeyChange: (value: string) => void;
  onTestConnection: () => void;
  onApplyConnection: () => void;
  onRefresh: () => void;
  onResetStoredSettings: () => void;
};

export function ConnectionPanel({
  activeBaseUrl,
  catalogStatus,
  connectionDraft,
  connectionTestStatus,
  settingsStatus,
  hasDraftChanges,
  model,
  agentId,
  sessionKey,
  agents,
  onConnectionDraftChange,
  onModelChange,
  onAgentIdChange,
  onSessionKeyChange,
  onTestConnection,
  onApplyConnection,
  onRefresh,
  onResetStoredSettings,
}: ConnectionPanelProps) {
  return (
    <Card className="panel wide-panel compact-panel">
      <Card.Header className="panel-header">
        <div className="panel-title">
          <Settings size={18} />
          <span>Connection</span>
        </div>
        <div className="editor-actions">
          <span>{hasDraftChanges ? "draft changes" : catalogStatus}</span>
          <Button size="sm" variant="secondary" onPress={onTestConnection}>
            <PlugZap size={15} />
            Test
          </Button>
          <Button size="sm" variant="secondary" onPress={onApplyConnection} isDisabled={!hasDraftChanges}>
            <Cable size={15} />
            Apply
          </Button>
          <Button size="sm" variant="secondary" onPress={onRefresh}>
            <RefreshCw size={15} />
            Refresh
          </Button>
        </div>
      </Card.Header>
      <Card.Content className="panel-content">
        <div className="connection-summary">
          <div>
            <span>Active server</span>
            <strong>{activeBaseUrl}</strong>
          </div>
          <div>
            <span>Catalog</span>
            <strong>{catalogStatus}</strong>
          </div>
          <div>
            <span>Connection test</span>
            <strong>{connectionTestStatus}</strong>
          </div>
          <div>
            <span>Settings</span>
            <strong>{settingsStatus}</strong>
          </div>
        </div>
        <section className="config-bar">
          <label className="control-label">
            <span>Server</span>
            <Input
              value={connectionDraft.baseUrl}
              onChange={(event) => onConnectionDraftChange("baseUrl", event.target.value)}
              aria-label="Server"
            />
          </label>
          <label className="control-label">
            <span>API key</span>
            <Input
              type="password"
              value={connectionDraft.apiKey}
              onChange={(event) => onConnectionDraftChange("apiKey", event.target.value)}
              aria-label="API key"
            />
          </label>
          <label className="control-label">
            <span>Admin key</span>
            <Input
              type="password"
              value={connectionDraft.adminKey}
              onChange={(event) => onConnectionDraftChange("adminKey", event.target.value)}
              aria-label="Admin key"
            />
          </label>
          <label className="control-label">
            <span>Model</span>
            <Input value={model} onChange={(event) => onModelChange(event.target.value)} aria-label="Model" />
          </label>
          <label className="control-label">
            <span>Agent</span>
            <select className="native-select" aria-label="Agent" value={agentId} onChange={(event) => onAgentIdChange(event.target.value)}>
              {(agents.length ? agents : [{ agent_id: agentId }]).map((agent) => (
                <option key={agent.agent_id} value={agent.agent_id}>
                  {agent.agent_id}
                </option>
              ))}
            </select>
          </label>
          <label className="control-label">
            <span>Session</span>
            <Input value={sessionKey} onChange={(event) => onSessionKeyChange(event.target.value)} aria-label="Session" />
          </label>
        </section>
        <div className="connection-actions">
          <Button size="sm" variant="secondary" onPress={onResetStoredSettings}>
            Reset
          </Button>
          <span>Saved in this browser. API and admin keys are never written back to the agent workspace.</span>
        </div>
      </Card.Content>
    </Card>
  );
}
