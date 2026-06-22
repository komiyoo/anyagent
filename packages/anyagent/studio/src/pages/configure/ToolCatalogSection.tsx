import { Button, Input } from "@heroui/react";
import { useMemo, useState } from "react";
import { ToolCatalog } from "../../anyagentClient";
import { csvToList } from "../../studioUtils";
import { CompactTable, EmptyState, StatusBadge } from "../../components/design-system";

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

type ToolEntry = ToolCatalog["tools"][number];

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

  const effectiveColumns = [
    { key: "name", header: "Name", render: (t: ToolEntry) => <strong className="ds-cell-strong">{t.name}</strong> },
    {
      key: "kind",
      header: "Kind",
      align: "left" as const,
      width: "110px",
      render: (t: ToolEntry) => (
        <StatusBadge status={t.kind === "command" ? "info" : "neutral"} dot={false}>
          {t.kind || t.reason || "tool"}
        </StatusBadge>
      ),
    },
    {
      key: "desc",
      header: "Description",
      render: (t: ToolEntry) => <span className="ds-cell-sub">{t.description || "No description"}</span>,
    },
  ];

  const availableColumns = [
    { key: "name", header: "Name", render: (t: ToolEntry) => <strong className="ds-cell-strong">{t.name}</strong> },
    {
      key: "kind",
      header: "Kind",
      width: "110px",
      render: (t: ToolEntry) => (
        <StatusBadge status={t.kind === "command" ? "info" : "neutral"} dot={false}>
          {t.kind || t.reason || "tool"}
        </StatusBadge>
      ),
    },
    {
      key: "desc",
      header: "Description",
      render: (t: ToolEntry) => <span className="ds-cell-sub">{t.description || "No description"}</span>,
    },
    {
      key: "state",
      header: "State",
      align: "right" as const,
      width: "100px",
      render: (t: ToolEntry) => {
        const enabled = requestedTools.includes(t.name);
        return (
          <button
            className={`capsule-toggle ${enabled ? "enabled" : ""}`}
            type="button"
            onClick={() => onToggleRequestedTool(t.name)}
          >
            {enabled ? "Enabled" : "Disabled"}
          </button>
        );
      },
    },
  ];

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
              <EmptyState
                compact
                title="No tools loaded"
                description="No tools are currently visible to this agent."
                action={
                  <Button size="sm" variant="primary" onPress={onLoadToolCatalog}>
                    Load tools
                  </Button>
                }
              />
            ) : (
              effectiveGroups.map(([kind, tools]) => (
                <section className="tool-kind-group" key={`effective-${kind}`}>
                  <strong>{kind}</strong>
                  <CompactTable
                    columns={effectiveColumns}
                    rows={tools ?? []}
                    rowKey={(t) => `effective-${t.name}`}
                  />
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
              <EmptyState
                compact
                title="No registered tools found"
                description="Load the registered tool pool before editing requested tools."
                action={
                  <Button size="sm" variant="primary" onPress={onLoadAvailableTools}>
                    Load available tools
                  </Button>
                }
              />
            ) : (
              availableGroups.map(([kind, tools]) => (
                <section className="tool-kind-group" key={`available-${kind}`}>
                  <strong>{kind}</strong>
                  <CompactTable
                    columns={availableColumns}
                    rows={tools ?? []}
                    rowKey={(t) => `available-${t.name}`}
                  />
                </section>
              ))
            )}
          </div>
        </>
      ) : null}
    </div>
  );
}
