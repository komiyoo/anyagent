import { Button, Chip, Input } from "@heroui/react";
import { useMemo, useState } from "react";
import { ToolCatalog } from "../../anyagentClient";
import { csvToList } from "../../studioUtils";

type ToolCatalogSectionProps = {
  toolCatalog: ToolCatalog | null;
  toolCatalogStatus?: string;
  availableTools: ToolCatalog | null;
  availableToolsStatus?: string;
  requestedToolsText: string;
  onLoadToolCatalog: () => void;
  onLoadAvailableTools: () => void;
  onToggleRequestedTool: (name: string) => void;
  showEffectiveTools?: boolean;
  showAvailableTools?: boolean;
};

function groupTools(tools: ToolCatalog["tools"]) {
  return tools.reduce<Array<[string, ToolCatalog["tools"]]>>((groups, tool) => {
    const kind = tool.kind || tool.reason || "tool";
    const existing = groups.find(([groupKind]) => groupKind === kind);
    if (existing) {
      existing[1].push(tool);
    } else {
      groups.push([kind, [tool]]);
    }
    return groups;
  }, []);
}

export function ToolCatalogSection({
  toolCatalog,
  toolCatalogStatus,
  availableTools,
  availableToolsStatus,
  requestedToolsText,
  onLoadToolCatalog,
  onLoadAvailableTools,
  onToggleRequestedTool,
  showEffectiveTools = true,
  showAvailableTools = true,
}: ToolCatalogSectionProps) {
  const requestedTools = csvToList(requestedToolsText);
  const [toolFilter, setToolFilter] = useState("");
  const filterTools = (tools: ToolCatalog["tools"]) => {
    const needle = toolFilter.trim().toLowerCase();
    if (!needle) {
      return tools;
    }
    return tools.filter((tool) =>
      [tool.name, tool.description, tool.kind, tool.reason].some((value) => String(value ?? "").toLowerCase().includes(needle)),
    );
  };
  const effectiveGroups = useMemo(() => {
    const tools = filterTools(toolCatalog?.tools ?? []);
    return groupTools(tools);
  }, [toolCatalog?.tools, toolFilter]);
  const availableGroups = useMemo(() => {
    const tools = filterTools(availableTools?.tools ?? []);
    return groupTools(tools);
  }, [availableTools?.tools, toolFilter]);

  return (
    <div className="tool-catalog">
      <div className="filter-row">
        <Input aria-label="Search tools" placeholder="Search tools by name, kind, description" value={toolFilter} onChange={(event) => setToolFilter(event.target.value)} />
      </div>
      {showEffectiveTools ? (
        <>
          <div className="subsection-heading">
            <span>Effective tools</span>
            <Button size="sm" variant="secondary" onPress={onLoadToolCatalog}>
              Refresh
            </Button>
            {toolCatalogStatus ? <em>{toolCatalogStatus}</em> : null}
          </div>
          <div className="tool-list">
            {!toolCatalog || toolCatalog.tools.length === 0 ? (
              <div className="empty-state compact-empty">
                <strong>No tools loaded</strong>
                <p>No tools are currently visible to this agent.</p>
                <Button size="sm" variant="primary" onPress={onLoadToolCatalog}>
                  Load tools
                </Button>
              </div>
            ) : (
              effectiveGroups.map(([kind, tools]) => (
                <section className="tool-kind-group" key={`effective-${kind}`}>
                  <strong>{kind}</strong>
                  {(tools ?? []).map((tool) => (
                    <article className="tool-row" key={`effective-${tool.name}`}>
                      <div>
                        <strong>{tool.name}</strong>
                        <span>{tool.description || "No description"}</span>
                      </div>
                      <Chip size="sm" variant="soft" color={tool.kind === "command" ? "accent" : "default"}>
                        {tool.kind || tool.reason || "tool"}
                      </Chip>
                    </article>
                  ))}
                </section>
              ))
            )}
          </div>
        </>
      ) : null}
      {showAvailableTools ? (
        <>
          <div className="subsection-heading">
            <span>Available tools</span>
            <Button size="sm" variant="secondary" onPress={onLoadAvailableTools}>
              Refresh
            </Button>
            {availableToolsStatus ? <em>{availableToolsStatus}</em> : null}
          </div>
          <div className="tool-list">
            {!availableTools || availableTools.tools.length === 0 ? (
              <div className="empty-state compact-empty">
                <strong>No registered tools found</strong>
                <p>Load the registered tool pool before editing requested tools.</p>
                <Button size="sm" variant="primary" onPress={onLoadAvailableTools}>
                  Load available tools
                </Button>
              </div>
            ) : (
              availableGroups.map(([kind, tools]) => (
                <section className="tool-kind-group" key={`available-${kind}`}>
                  <strong>{kind}</strong>
                  {(tools ?? []).map((tool) => (
                    <article className="tool-row" key={`available-${tool.name}`}>
                      <div>
                        <strong>{tool.name}</strong>
                        <span>{tool.description || "No description"}</span>
                      </div>
                      <button
                        className={`capsule-toggle ${requestedTools.includes(tool.name) ? "enabled" : ""}`}
                        type="button"
                        onClick={() => onToggleRequestedTool(tool.name)}
                      >
                        {requestedTools.includes(tool.name) ? "Enabled" : "Disabled"}
                      </button>
                    </article>
                  ))}
                </section>
              ))
            )}
          </div>
        </>
      ) : null}
    </div>
  );
}
