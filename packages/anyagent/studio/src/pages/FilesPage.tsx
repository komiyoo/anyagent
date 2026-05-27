import { Button, Card, TextArea } from "@heroui/react";
import { FileText, RefreshCw } from "lucide-react";
import { AgentFileKind, AgentWorkspaceFile } from "../anyagentClient";
import { fileByKind, fileLabels, shortHash } from "../studioUtils";

const FILE_KINDS: AgentFileKind[] = ["agents_md", "agent_yaml", "mcp_json"];

type FilesPageProps = {
  files: AgentWorkspaceFile[];
  activeFileKind: AgentFileKind;
  enabledFileKinds: AgentFileKind[];
  editorText: string;
  saveStatus: string;
  onActiveFileKindChange: (kind: AgentFileKind) => void;
  onEditorTextChange: (value: string) => void;
  onToggleFileKind: (kind: AgentFileKind) => void;
  onReloadFiles: () => void;
  onSaveActiveFile: () => void;
};

export function FilesPage({
  files,
  activeFileKind,
  enabledFileKinds,
  editorText,
  saveStatus,
  onActiveFileKindChange,
  onEditorTextChange,
  onToggleFileKind,
  onReloadFiles,
  onSaveActiveFile,
}: FilesPageProps) {
  const activeFile = fileByKind(files, activeFileKind);
  const isActiveEditorEnabled = enabledFileKinds.includes(activeFileKind);

  return (
    <Card className="panel editor-panel">
      <Card.Header className="panel-header">
        <div className="panel-title">
          <FileText size={18} />
          <span>Agent pack source</span>
        </div>
        <div className="editor-actions">
          <span>{saveStatus}</span>
          <Button size="sm" variant="secondary" onPress={onReloadFiles}>
            <RefreshCw size={15} />
            Reload
          </Button>
          <Button size="sm" variant="primary" onPress={onSaveActiveFile}>
            Save
          </Button>
        </div>
      </Card.Header>
      <Card.Content className="panel-content">
        <div className="file-tabs" role="tablist" aria-label="Agent files">
          {FILE_KINDS.map((kind) => {
            const file = fileByKind(files, kind);
            return (
              <button className={activeFileKind === kind ? "active" : ""} type="button" key={`files-${kind}`} onClick={() => onActiveFileKindChange(kind)}>
                <span>{fileLabels[kind]}</span>
                <em>{file?.sha256 ? shortHash(file.sha256) : "new"}</em>
                <i>{enabledFileKinds.includes(kind) ? "Active" : "Disabled"}</i>
              </button>
            );
          })}
        </div>
        <button
          className={`capsule-toggle file-enable-toggle ${isActiveEditorEnabled ? "enabled" : ""}`}
          type="button"
          onClick={() => onToggleFileKind(activeFileKind)}
        >
          {isActiveEditorEnabled ? "Active editor" : "Editor disabled"}
        </button>
        <div className="file-path">{activeFile?.path ?? "No file loaded"}</div>
        <TextArea
          className="source-editor"
          aria-label={`${fileLabels[activeFileKind]} source`}
          rows={22}
          value={editorText}
          onChange={(event) => onEditorTextChange(event.target.value)}
          readOnly={!isActiveEditorEnabled}
        />
      </Card.Content>
    </Card>
  );
}
