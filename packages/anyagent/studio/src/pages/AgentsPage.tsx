import { Button, Card, Chip, Input, TextArea } from "@heroui/react";
import { Bot, MessageSquareText, Play, RefreshCw, Sparkles, SquarePen } from "lucide-react";
import { FormEvent, useMemo, useState } from "react";
import { AgentDetail, AgentSummary, McpServerDraft, StudioSettings, ToolCatalog } from "../anyagentClient";
import { StudioMode, StudioTab } from "../navigation";
import { formatCount } from "../studioUtils";

type AgentsPageProps = {
  mode: StudioMode;
  agents: AgentSummary[];
  settings: StudioSettings;
  agentDetail: AgentDetail | null;
  skillCount: number;
  selectedSkillCount: number;
  toolCatalog: ToolCatalog | null;
  mcpDrafts: McpServerDraft[];
  agentCreateStatus: string;
  newAgentId: string;
  newAgentTools: string;
  newAgentInstructions: string;
  onSelectAgent: (agentId: string) => void;
  onRefresh: () => void;
  onNavigate: (tab: StudioTab) => void;
  onCreateAgent: (event: FormEvent<HTMLFormElement>) => void;
  onNewAgentIdChange: (value: string) => void;
  onNewAgentToolsChange: (value: string) => void;
  onNewAgentInstructionsChange: (value: string) => void;
};

export function AgentsPage({
  mode,
  agents,
  settings,
  agentDetail,
  skillCount,
  selectedSkillCount,
  toolCatalog,
  mcpDrafts,
  agentCreateStatus,
  newAgentId,
  newAgentTools,
  newAgentInstructions,
  onSelectAgent,
  onRefresh,
  onNavigate,
  onCreateAgent,
  onNewAgentIdChange,
  onNewAgentToolsChange,
  onNewAgentInstructionsChange,
}: AgentsPageProps) {
  const [agentFilter, setAgentFilter] = useState("");
  const visibleAgents = useMemo(() => {
    const agentList = agents.length ? agents : [{ agent_id: settings.agentId }];
    const needle = agentFilter.trim().toLowerCase();
    if (!needle) {
      return agentList;
    }
    return agentList.filter((agent) =>
      [agent.agent_id, agent.model_default, agent.model_provider, agent.sandbox_mode].some((value) =>
        String(value ?? "").toLowerCase().includes(needle),
      ),
    );
  }, [agentFilter, agents, settings.agentId]);

  return (
    <>
      <section className="section-block">
        <div className="section-title">
          <Bot size={17} />
          <h2>{mode === "use" ? "Choose an agent" : "Agent packs"}</h2>
          <span>{mode === "use" ? "Use an exposed workspace agent" : `${agents.length} workspace agents`}</span>
        </div>
        <div className="filter-row">
          <Input aria-label="Search agents" placeholder="Search agents by name, model, provider" value={agentFilter} onChange={(event) => setAgentFilter(event.target.value)} />
        </div>
        <div className="agent-directory">
          {visibleAgents.map((agent) => (
            <button
              className={`agent-directory-row ${settings.agentId === agent.agent_id ? "active" : ""}`}
              key={agent.agent_id}
              type="button"
              onClick={() => onSelectAgent(agent.agent_id)}
            >
              <div>
                <strong>{agent.agent_id}</strong>
                <span>{agent.exposed === false ? "hidden" : "exposed"} · workspace agent</span>
              </div>
              <Chip size="sm" variant="soft" color={settings.agentId === agent.agent_id ? "success" : "default"}>
                {settings.agentId === agent.agent_id ? "active" : "select"}
              </Chip>
            </button>
          ))}
        </div>
      </section>

      <div className="main-grid">
        <Card className="panel">
          <Card.Header className="panel-header">
            <div className="panel-title">
              <Bot size={18} />
              <span>{mode === "use" ? "Agent profile" : "Selected agent"}</span>
            </div>
            <Button size="sm" variant="secondary" onPress={onRefresh}>
              <RefreshCw size={15} />
              Refresh
            </Button>
          </Card.Header>
          <Card.Content className="panel-content">
            <div className="breakdown-list">
              <div className="breakdown-row">
                <span>Agent ID</span>
                <strong>{settings.agentId || "-"}</strong>
              </div>
              <div className="breakdown-row">
                <span>Model</span>
                <strong>{agentDetail?.model?.default ?? agentDetail?.model_default ?? settings.model}</strong>
              </div>
              <div className="breakdown-row">
                <span>Sandbox</span>
                <strong>{agentDetail?.sandbox?.mode ?? agentDetail?.sandbox_mode ?? "-"}</strong>
              </div>
              <div className="breakdown-row">
                <span>Requested tools</span>
                <strong>{formatCount((agentDetail?.tools?.requested_tool_names ?? agentDetail?.requested_tool_names ?? []).length)}</strong>
              </div>
              <div className="breakdown-row">
                <span>Skills</span>
                <strong>{formatCount(skillCount)}</strong>
              </div>
            </div>
            {mode === "use" ? (
              <div className="connection-actions">
                <Button size="sm" variant="primary" onPress={() => onNavigate("home")}>
                  <Play size={13} />
                  Start session
                </Button>
                <Button size="sm" variant="secondary" onPress={() => onNavigate("sessions")}>
                  <MessageSquareText size={13} />
                  View sessions
                </Button>
              </div>
            ) : null}
          </Card.Content>
        </Card>

        {mode === "build" ? (
          <Card className="panel">
            <Card.Header className="panel-header">
              <div className="panel-title">
                <SquarePen size={18} />
                <span>Create agent</span>
              </div>
              <span className="status-line">{agentCreateStatus}</span>
            </Card.Header>
            <Card.Content className="panel-content">
              <form className="agent-create-stacked" onSubmit={onCreateAgent}>
                <Input aria-label="New agent id" value={newAgentId} onChange={(event) => onNewAgentIdChange(event.target.value)} />
                <Input aria-label="Requested tools" value={newAgentTools} onChange={(event) => onNewAgentToolsChange(event.target.value)} />
                <TextArea
                  aria-label="New agent instructions"
                  rows={5}
                  value={newAgentInstructions}
                  onChange={(event) => onNewAgentInstructionsChange(event.target.value)}
                />
                <Button type="submit" variant="primary">
                  Create agent
                </Button>
              </form>
            </Card.Content>
          </Card>
        ) : (
          <Card className="panel">
            <Card.Header className="panel-header">
              <div className="panel-title">
                <Sparkles size={18} />
                <span>Available capabilities</span>
              </div>
            </Card.Header>
            <Card.Content className="panel-content">
              <div className="breakdown-list">
                <div className="breakdown-row">
                  <span>Default skills</span>
                  <strong>{formatCount(selectedSkillCount)}</strong>
                </div>
                <div className="breakdown-row">
                  <span>Visible tools</span>
                  <strong>{formatCount(toolCatalog?.tools.length ?? 0)}</strong>
                </div>
                <div className="breakdown-row">
                  <span>MCP servers</span>
                  <strong>{formatCount(mcpDrafts.filter((draft) => draft.enabled).length)}</strong>
                </div>
              </div>
            </Card.Content>
          </Card>
        )}
      </div>
    </>
  );
}
