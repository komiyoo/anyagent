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
  const isCreating = agentCreateStatus === "Creating";
  const agentIdError = newAgentId.trim() && !/^[a-zA-Z0-9._-]+$/.test(newAgentId.trim()) ? "Use letters, numbers, dot, dash, or underscore." : "";
  const instructionsError = newAgentInstructions.trim() ? "" : "Instructions are required.";

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
          <label className="control-label">
            <span>Agent id</span>
            <Input aria-label="New agent id" value={newAgentId} onChange={(event) => onNewAgentIdChange(event.target.value)} />
            {agentIdError ? <small className="field-error">{agentIdError}</small> : null}
          </label>
          <label className="control-label">
            <span>Requested tools</span>
            <Input aria-label="Requested tools" value={newAgentTools} onChange={(event) => onNewAgentToolsChange(event.target.value)} />
          </label>
          <label className="control-label">
            <span>Instructions</span>
            <TextArea
              aria-label="New agent instructions"
              rows={2}
              value={newAgentInstructions}
              onChange={(event) => onNewAgentInstructionsChange(event.target.value)}
            />
            {instructionsError ? <small className="field-error">{instructionsError}</small> : null}
          </label>
          <Button type="submit" variant="primary" isDisabled={isCreating || Boolean(agentIdError) || Boolean(instructionsError)}>
            {isCreating ? <span className="button-spinner" aria-hidden="true" /> : null}
            Create agent
          </Button>
        </form>
      </Card.Content>
    </Card>
  );
}
