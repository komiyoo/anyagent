import { Button, Card, Input, TextArea } from "@heroui/react";
import { SquarePen } from "lucide-react";
import { FormEventHandler } from "react";

type CreateAgentPanelProps = {
  agentCreateStatus: string;
  newAgentId: string;
  newAgentTools: string;
  newAgentInstructions: string;
  onSubmit: FormEventHandler<HTMLFormElement>;
  onNewAgentIdChange: (value: string) => void;
  onNewAgentToolsChange: (value: string) => void;
  onNewAgentInstructionsChange: (value: string) => void;
};

export function CreateAgentPanel({
  agentCreateStatus,
  newAgentId,
  newAgentTools,
  newAgentInstructions,
  onSubmit,
  onNewAgentIdChange,
  onNewAgentToolsChange,
  onNewAgentInstructionsChange,
}: CreateAgentPanelProps) {
  return (
    <Card className="panel wide-panel compact-panel">
      <Card.Header className="panel-header">
        <div className="panel-title">
          <SquarePen size={18} />
          <span>Create agent</span>
        </div>
        <span className="status-line">{agentCreateStatus}</span>
      </Card.Header>
      <Card.Content className="panel-content">
        <form className="agent-create-bar" onSubmit={onSubmit}>
          <Input aria-label="New agent id" value={newAgentId} onChange={(event) => onNewAgentIdChange(event.target.value)} />
          <Input aria-label="Requested tools" value={newAgentTools} onChange={(event) => onNewAgentToolsChange(event.target.value)} />
          <TextArea
            aria-label="New agent instructions"
            rows={2}
            value={newAgentInstructions}
            onChange={(event) => onNewAgentInstructionsChange(event.target.value)}
          />
          <Button type="submit" variant="primary">
            Create agent
          </Button>
        </form>
      </Card.Content>
    </Card>
  );
}
