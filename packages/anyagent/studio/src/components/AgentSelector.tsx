import { useRef, useState } from "react";
import { Chip } from "@heroui/react";
import { ChevronDown, Bot } from "lucide-react";
import { AgentSummary } from "../anyagentClient";

type AgentSelectorProps = {
  agents: AgentSummary[];
  currentAgentId: string;
  onChangeAgent: (agentId: string) => void;
};

export function AgentSelector({ agents, currentAgentId, onChangeAgent }: AgentSelectorProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const exposedAgents = agents.filter((a) => a.exposed !== false);

  return (
    <div className="agent-selector" ref={containerRef}>
      <button
        className="agent-selector-trigger"
        onClick={() => setOpen((v) => !v)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
      >
        <Bot size={12} />
        <span className="agent-selector-value">{currentAgentId || "main"}</span>
        <ChevronDown size={12} />
      </button>
      {open && (
        <div className="agent-selector-dropdown">
          {exposedAgents.map((agent) => (
            <button
              key={agent.agent_id}
              className={`agent-selector-option ${agent.agent_id === currentAgentId ? "active" : ""}`}
              onClick={() => { onChangeAgent(agent.agent_id); setOpen(false); }}
            >
              <span className="agent-selector-option-id">{agent.agent_id}</span>
              {agent.model_default && (
                <Chip size="sm" variant="soft">{agent.model_default}</Chip>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
