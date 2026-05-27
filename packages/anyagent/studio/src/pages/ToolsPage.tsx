import { Card } from "@heroui/react";
import { Wrench } from "lucide-react";
import { ToolCatalog } from "../anyagentClient";
import { ToolCatalogSection } from "./configure/ToolCatalogSection";

type ToolsPageProps = {
  toolCatalog: ToolCatalog | null;
  availableTools: ToolCatalog | null;
  requestedToolsText: string;
  onLoadToolCatalog: () => void;
  onLoadAvailableTools: () => void;
  onToggleRequestedTool: (name: string) => void;
};

export function ToolsPage({
  toolCatalog,
  availableTools,
  requestedToolsText,
  onLoadToolCatalog,
  onLoadAvailableTools,
  onToggleRequestedTool,
}: ToolsPageProps) {
  return (
    <div className="main-grid configure-grid">
      <Card className="panel wide-panel">
        <Card.Header className="panel-header">
          <div className="panel-title">
            <Wrench size={18} />
            <span>Tool catalog</span>
          </div>
        </Card.Header>
        <Card.Content className="panel-content">
          <ToolCatalogSection
            toolCatalog={toolCatalog}
            availableTools={availableTools}
            requestedToolsText={requestedToolsText}
            onLoadToolCatalog={onLoadToolCatalog}
            onLoadAvailableTools={onLoadAvailableTools}
            onToggleRequestedTool={onToggleRequestedTool}
          />
        </Card.Content>
      </Card>
    </div>
  );
}
