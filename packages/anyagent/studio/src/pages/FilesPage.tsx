import { Button, Card, TextArea } from "@heroui/react";
import { FileText, RefreshCw } from "lucide-react";
import { useMemo } from "react";
import { AgentFileKind, AgentWorkspaceFile } from "../anyagentClient";
import { fileByKind, fileLabels, shortHash } from "../studioUtils";
import { StatStrip } from "../components/design-system";
import type { StatItem } from "../components/design-system";

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

  // 轻量校验：mcp.json 用 JSON.parse，agent.yaml/AGENTS.md 仅做基本非空提示。
  // 不阻断保存，仅实时反馈格式问题。
  const validationResult = useMemo(() => {
    if (!editorText.trim()) return { ok: true, message: "empty" };
    if (activeFileKind === "mcp_json") {
      try {
        JSON.parse(editorText);
        return { ok: true, message: "valid JSON" };
      } catch (error) {
        return { ok: false, message: error instanceof Error ? error.message : "invalid JSON" };
      }
    }
    if (activeFileKind === "agent_yaml") {
      // 基本检查：tab 缩进在 YAML 中非法
      if (/\t/.test(editorText)) {
        return { ok: false, message: "YAML 不允许 Tab 缩进，请用空格" };
      }
      return { ok: true, message: "YAML" };
    }
    return { ok: true, message: "markdown" };
  }, [editorText, activeFileKind]);

  const fileStats: StatItem[] = FILE_KINDS.map((kind) => {
    const file = fileByKind(files, kind);
    return {
      label: fileLabels[kind],
      value: file?.sha256 ? shortHash(file.sha256) : "new",
      tone: enabledFileKinds.includes(kind) ? "success" : "default",
    };
  });

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
        <StatStrip stats={fileStats} className="ds-files-stats" />
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
        <div className={`ds-editor-validate ${validationResult.ok ? "ds-editor-validate--ok" : "ds-editor-validate--err"}`} role="status">
          <span className="ds-editor-validate-dot" aria-hidden="true" />
          <span className="ds-editor-validate-msg">{validationResult.message}</span>
        </div>
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
