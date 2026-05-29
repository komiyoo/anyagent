import { Button, Chip } from "@heroui/react";
import { MessageSquareText, PanelLeftClose, PanelLeftOpen, Plus, Trash2 } from "lucide-react";
import { StudioConversation } from "../stores/chatStore";

type ConversationSidebarProps = {
  conversations: StudioConversation[];
  activeConversationId: string;
  open: boolean;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onToggle: () => void;
};

export function ConversationSidebar({
  conversations,
  activeConversationId,
  open,
  onSelect,
  onNew,
  onDelete,
  onRename,
  onToggle,
}: ConversationSidebarProps) {
  if (!open) {
    return null;
  }

  return (
    <aside className="conversation-sidebar">
      <div className="conversation-sidebar-header">
        <span className="conversation-sidebar-title">Conversations</span>
        <div className="conversation-sidebar-actions">
          <Button size="sm" variant="ghost" isIconOnly onPress={onNew}>
            <Plus size={14} />
          </Button>
          <Button size="sm" variant="ghost" isIconOnly onPress={onToggle}>
            <PanelLeftClose size={14} />
          </Button>
        </div>
      </div>
      <div className="conversation-sidebar-list">
        {conversations.map((conv) => (
          <div
            key={conv.id}
            className={`conversation-sidebar-row ${conv.id === activeConversationId ? "active" : ""}`}
            onClick={() => onSelect(conv.id)}
            onDoubleClick={() => {
              const newTitle = window.prompt("Rename conversation", conv.title);
              if (newTitle !== null) onRename(conv.id, newTitle);
            }}
          >
            <div className="conversation-sidebar-row-main">
              <MessageSquareText size={14} className="conversation-sidebar-icon" />
              <span className="conversation-sidebar-row-title">{conv.title}</span>
            </div>
            <div className="conversation-sidebar-row-meta">
              <Chip size="sm" variant="soft" className="conversation-sidebar-agent-chip">
                {conv.agentId || "main"}
              </Chip>
              <span className="conversation-sidebar-row-count">{conv.messages.filter((m) => m.role === "user").length}</span>
              <button
                className="conversation-sidebar-delete"
                onClick={(e) => { e.stopPropagation(); onDelete(conv.id); }}
                title="Delete"
              >
                <Trash2 size={12} />
              </button>
            </div>
          </div>
        ))}
      </div>
    </aside>
  );
}
