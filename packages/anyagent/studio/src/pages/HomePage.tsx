import { Button, Card, Chip, TextArea } from "@heroui/react";
import { Activity, Braces, Cable, MessageSquareText, Send, SlidersHorizontal, Sparkles } from "lucide-react";
import { FormEvent } from "react";
import { AgentDetail, AgentWorkspaceFile, ChatMessage, CredentialRef, McpServerDraft, StudioDebugEvent, StudioSettings, ToolCatalog } from "../anyagentClient";
import { StudioMode, StudioTab } from "../navigation";
import { compactJson, formatCount, shortHash } from "../studioUtils";

type TraceRow = {
  name: string;
  latest: string;
  traces: number;
  errors: string;
  p50: string;
  p99: string;
  description: string;
};

type HomePageProps = {
  mode: StudioMode;
  settings: StudioSettings;
  agentDetail: AgentDetail | null;
  skillCount: number;
  selectedSkillCount: number;
  mcpDrafts: McpServerDraft[];
  toolCatalog: ToolCatalog | null;
  toolCatalogStatus: string;
  agentFiles: AgentWorkspaceFile[];
  credentials: CredentialRef[];
  availableTools: ToolCatalog | null;
  adminStatus: string;
  traceRows: TraceRow[];
  messages: ChatMessage[];
  input: string;
  isRunning: boolean;
  streamEvents: StudioDebugEvent[];
  onInputChange: (value: string) => void;
  onSubmitChat: (event: FormEvent<HTMLFormElement>) => void;
  onNavigate: (tab: StudioTab) => void;
};

export function HomePage({
  mode,
  settings,
  agentDetail,
  skillCount,
  selectedSkillCount,
  mcpDrafts,
  toolCatalog,
  toolCatalogStatus,
  agentFiles,
  credentials,
  availableTools,
  adminStatus,
  traceRows,
  messages,
  input,
  isRunning,
  streamEvents,
  onInputChange,
  onSubmitChat,
  onNavigate,
}: HomePageProps) {
  if (mode === "build") {
    return (
      <>
        <section className="section-block">
          <div className="section-title">
            <SlidersHorizontal size={17} />
            <h2>Build workspace</h2>
            <span>{settings.agentId || "main"} configuration health</span>
          </div>
          <div className="metric-grid compact-metrics">
            <Card className="metric-card">
              <Card.Content>
                <span>Agent</span>
                <strong>{settings.agentId || "-"}</strong>
                <small>{agentDetail?.exposed === false ? "hidden" : "exposed"}</small>
              </Card.Content>
            </Card>
            <Card className="metric-card">
              <Card.Content>
                <span>Skills</span>
                <strong>{formatCount(skillCount)}</strong>
                <small>{formatCount(selectedSkillCount)} default selected</small>
              </Card.Content>
            </Card>
            <Card className="metric-card">
              <Card.Content>
                <span>MCP</span>
                <strong>{formatCount(mcpDrafts.length)}</strong>
                <small>{mcpDrafts.filter((draft) => draft.enabled).length} enabled</small>
              </Card.Content>
            </Card>
            <Card className="metric-card">
              <Card.Content>
                <span>Tools</span>
                <strong>{formatCount(toolCatalog?.tools.length ?? 0)}</strong>
                <small>{toolCatalogStatus}</small>
              </Card.Content>
            </Card>
          </div>
        </section>

        <div className="main-grid">
          <Card className="panel">
            <Card.Header className="panel-header">
              <div className="panel-title">
                <Braces size={18} />
                <span>Configuration checklist</span>
              </div>
            </Card.Header>
            <Card.Content className="panel-content">
              <div className="breakdown-list">
                <button className="suggestion-row" type="button" onClick={() => onNavigate("configure")}>
                  <strong>Agent config</strong>
                  <span>Model, sandbox, requested tools, spawn boundaries</span>
                </button>
                <button className="suggestion-row" type="button" onClick={() => onNavigate("skills")}>
                  <strong>Skills</strong>
                  <span>Install/update skills and choose default selected skills</span>
                </button>
                <button className="suggestion-row" type="button" onClick={() => onNavigate("mcp")}>
                  <strong>MCP servers</strong>
                  <span>Manage transports, enabled state, and credential references</span>
                </button>
                <button className="suggestion-row" type="button" onClick={() => onNavigate("files")}>
                  <strong>Source files</strong>
                  <span>Edit AGENTS.md, agent.yaml, and mcp.json with sha256 guards</span>
                </button>
              </div>
            </Card.Content>
          </Card>

          <Card className="panel">
            <Card.Header className="panel-header">
              <div className="panel-title">
                <Activity size={18} />
                <span>Build signals</span>
              </div>
            </Card.Header>
            <Card.Content className="panel-content">
              <div className="breakdown-list">
                <div className="breakdown-row">
                  <span>Files</span>
                  <strong>{agentFiles.filter((file) => file.exists !== false).length}/{agentFiles.length || 3}</strong>
                </div>
                <div className="breakdown-row">
                  <span>Credentials</span>
                  <strong>{formatCount(credentials.length)}</strong>
                </div>
                <div className="breakdown-row">
                  <span>Available tools</span>
                  <strong>{formatCount(availableTools?.tools.length ?? 0)}</strong>
                </div>
                <div className="breakdown-row">
                  <span>Admin status</span>
                  <strong>{adminStatus}</strong>
                </div>
              </div>
            </Card.Content>
          </Card>
        </div>
      </>
    );
  }

  return (
    <>
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
            <form className="composer" onSubmit={onSubmitChat}>
              <TextArea
                rows={3}
                value={input}
                onChange={(event) => onInputChange(event.target.value)}
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
            <p>{selectedSkillCount} selected from {skillCount} available skills</p>
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
    </>
  );
}
