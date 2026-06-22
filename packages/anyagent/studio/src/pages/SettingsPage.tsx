import { Button, Card, Input } from "@heroui/react";
import { Bot, Cable, Database, KeyRound, PlugZap, RefreshCw, Settings } from "lucide-react";
import { AdminStatus, StudioSettings } from "../anyagentClient";
import { StudioMode } from "../navigation";
import { ConnectionDraft } from "../studioSettings";
import { compactJson } from "../studioUtils";
import { StatStrip } from "../components/design-system";
import type { StatItem } from "../components/design-system";

type SettingsPageProps = {
  mode: StudioMode;
  settings: StudioSettings;
  connectionDraft: ConnectionDraft;
  activeConnection: ConnectionDraft;
  hasConnectionDraftChanges: boolean;
  settingsStatus: string;
  adminStatus: string;
  catalogStatus: string;
  connectionTestStatus: string;
  serverHealth: AdminStatus | null;
  storageHealth: AdminStatus | null;
  credentialCapabilities: AdminStatus | null;
  onConnectionDraftChange: <K extends keyof ConnectionDraft>(key: K, value: ConnectionDraft[K]) => void;
  onSettingsChange: <K extends keyof StudioSettings>(key: K, value: StudioSettings[K]) => void;
  onTestConnection: () => void;
  onApplyConnection: () => void;
  onLoadAdminStatus: () => void;
  onReset: () => void;
};

export function SettingsPage({
  mode,
  settings,
  connectionDraft,
  activeConnection,
  hasConnectionDraftChanges,
  settingsStatus,
  adminStatus,
  catalogStatus,
  connectionTestStatus,
  serverHealth,
  storageHealth,
  credentialCapabilities,
  onConnectionDraftChange,
  onSettingsChange,
  onTestConnection,
  onApplyConnection,
  onLoadAdminStatus,
  onReset,
}: SettingsPageProps) {
  const isTesting = connectionTestStatus === "Testing";
  const isLoadingHealth = adminStatus === "Loading";
  const serverError = connectionDraft.baseUrl.trim() ? "" : "Server URL is required.";

  const healthTone = (status: string): StatItem["tone"] => {
    const value = status.toLowerCase();
    if (["ok", "ready", "healthy", "available", "configured"].includes(value)) return "success";
    if (["degraded", "loading", "pending", "testing", "saving"].includes(value)) return "warning";
    if (["error", "unavailable", "failed", "down", "missing"].includes(value)) return "error";
    return "default";
  };

  const healthStats: StatItem[] = [
    { label: "Active server", value: activeConnection.baseUrl || "-" },
    {
      label: "Server health",
      value: String(serverHealth?.status ?? adminStatus),
      tone: healthTone(String(serverHealth?.status ?? adminStatus)),
    },
    {
      label: "Storage",
      value: String(storageHealth?.status ?? "-"),
      tone: storageHealth ? healthTone(String(storageHealth.status)) : "default",
    },
    {
      label: "Credentials",
      value: credentialCapabilities ? "capabilities loaded" : "-",
      tone: credentialCapabilities ? "success" : "default",
    },
  ];

  return (
    <>
      <Card className="panel wide-panel compact-panel">
        <Card.Header className="panel-header">
          <div className="panel-title">
            <Settings size={18} />
            <span>{mode === "use" ? "Personal connection" : "Server management"}</span>
          </div>
          <div className="editor-actions">
            <span>{hasConnectionDraftChanges ? "draft changes" : settingsStatus}</span>
            <Button size="sm" variant="secondary" onPress={onTestConnection} isDisabled={isTesting || Boolean(serverError)}>
              {isTesting ? <span className="button-spinner" aria-hidden="true" /> : null}
              <PlugZap size={15} />
              Test
            </Button>
            <Button size="sm" variant="secondary" onPress={onApplyConnection} isDisabled={!hasConnectionDraftChanges || Boolean(serverError)}>
              <Cable size={15} />
              Apply
            </Button>
            <Button size="sm" variant="secondary" onPress={onLoadAdminStatus} isDisabled={isLoadingHealth}>
              {isLoadingHealth ? <span className="button-spinner" aria-hidden="true" /> : null}
              <RefreshCw size={15} />
              Health
            </Button>
          </div>
        </Card.Header>
        <Card.Content className="panel-content">
          <StatStrip stats={healthStats} className="ds-settings-health" />
          <section className="config-bar">
            <label className="control-label">
              <span>Server</span>
              <Input value={connectionDraft.baseUrl} onChange={(event) => onConnectionDraftChange("baseUrl", event.target.value)} aria-label="Server" />
              {serverError ? <small className="field-error">{serverError}</small> : null}
            </label>
            <label className="control-label">
              <span>API key</span>
              <Input type="password" value={connectionDraft.apiKey} onChange={(event) => onConnectionDraftChange("apiKey", event.target.value)} aria-label="API key" />
            </label>
            <label className="control-label">
              <span>Admin key</span>
              <Input type="password" value={connectionDraft.adminKey} onChange={(event) => onConnectionDraftChange("adminKey", event.target.value)} aria-label="Admin key" />
            </label>
            <label className="control-label">
              <span>Model</span>
              <Input value={settings.model} onChange={(event) => onSettingsChange("model", event.target.value)} aria-label="Model" />
            </label>
            <label className="control-label">
              <span>Agent</span>
              <Input value={settings.agentId} onChange={(event) => onSettingsChange("agentId", event.target.value)} aria-label="Agent" />
            </label>
            <label className="control-label">
              <span>Session</span>
              <Input value={settings.sessionKey} onChange={(event) => onSettingsChange("sessionKey", event.target.value)} aria-label="Session" />
            </label>
          </section>
          <div className="connection-actions">
            <Button size="sm" variant="secondary" onPress={onReset}>
              Reset
            </Button>
            <span>Settings are browser-local. Secrets are not written to agent pack files.</span>
          </div>
        </Card.Content>
      </Card>

      {mode === "build" ? (
        <div className="main-grid">
          <Card className="panel">
            <Card.Header className="panel-header">
              <div className="panel-title">
                <Database size={18} />
                <span>Storage health</span>
              </div>
            </Card.Header>
            <Card.Content className="panel-content">
              <pre className="json-preview compact-json">{storageHealth ? compactJson(storageHealth) : "No storage health loaded."}</pre>
            </Card.Content>
          </Card>
          <Card className="panel">
            <Card.Header className="panel-header">
              <div className="panel-title">
                <KeyRound size={18} />
                <span>Credential capabilities</span>
              </div>
            </Card.Header>
            <Card.Content className="panel-content">
              <pre className="json-preview compact-json">
                {credentialCapabilities ? compactJson(credentialCapabilities) : "No credential capability matrix loaded."}
              </pre>
            </Card.Content>
          </Card>
        </div>
      ) : (
        <div className="main-grid">
          <Card className="panel">
            <Card.Header className="panel-header">
              <div className="panel-title">
                <Bot size={18} />
                <span>Run defaults</span>
              </div>
            </Card.Header>
            <Card.Content className="panel-content">
              <div className="breakdown-list">
                <div className="breakdown-row">
                  <span>Agent</span>
                  <strong>{settings.agentId}</strong>
                </div>
                <div className="breakdown-row">
                  <span>Session</span>
                  <strong>{settings.sessionKey}</strong>
                </div>
                <div className="breakdown-row">
                  <span>Model</span>
                  <strong>{settings.model}</strong>
                </div>
              </div>
            </Card.Content>
          </Card>
          <Card className="panel">
            <Card.Header className="panel-header">
              <div className="panel-title">
                <PlugZap size={18} />
                <span>Connection status</span>
              </div>
            </Card.Header>
            <Card.Content className="panel-content">
              <div className="breakdown-list">
                <div className="breakdown-row">
                  <span>Catalog</span>
                  <strong>{catalogStatus}</strong>
                </div>
                <div className="breakdown-row">
                  <span>Test</span>
                  <strong>{connectionTestStatus}</strong>
                </div>
                <div className="breakdown-row">
                  <span>Server</span>
                  <strong>{activeConnection.baseUrl}</strong>
                </div>
              </div>
            </Card.Content>
          </Card>
        </div>
      )}
    </>
  );
}
