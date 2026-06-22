import { Button, Card, Chip } from "@heroui/react";
import {
  Activity,
  ArrowDown,
  Braces,
  Check,
  Copy,
  MessageSquareText,
  PanelLeftOpen,
  Pencil,
  PlugZap,
  Plus,
  RefreshCw,
  Send,
  SlidersHorizontal,
  Sparkles,
  Square,
  Trash2,
  User,
  Bot,
  ChevronDown,
  ChevronRight,
  Zap,
  PackagePlus,
  Puzzle,
  Terminal,
  Wrench,
} from "lucide-react";
import { FormEvent, KeyboardEvent, useCallback, useEffect, useRef, useState } from "react";
import { MarkdownMessage } from "../components/MarkdownMessage";
import { ConversationSidebar } from "../components/ConversationSidebar";
import { AgentSelector } from "../components/AgentSelector";
import { CompactTable, StatStrip } from "../components/design-system";
import { AgentDetail, AgentSummary, AgentWorkspaceFile, ChatMessage, CredentialRef, McpServerDraft, StudioSettings, ToolCallItem, ToolCatalog } from "../anyagentClient";
import { StudioMode, StudioTab } from "../navigation";
import { StudioConversation } from "../stores/chatStore";
import { formatCount, shortHash } from "../studioUtils";

type TraceRow = {
  name: string;
  latest: string;
  traces: number;
  errors: string;
  p50: string;
  p99: string;
  description: string;
};

/** 解析 trace 错误率字符串（如 "0%"、"4.2%"）返回 design-system tone class */
function traceErrorTone(errors: string): string {
  const value = Number.parseFloat(errors);
  if (!Number.isFinite(value)) return "";
  if (value <= 0) return "ds-text-success";
  if (value >= 5) return "ds-text-error";
  return "ds-text-warning";
}

type HomePageProps = {
  mode: StudioMode;
  settings: StudioSettings;
  agentDetail: AgentDetail | null;
  skillCount: number;
  selectedSkillCount: number;
  mcpDrafts: McpServerDraft[];
  toolCatalog: ToolCatalog | null;
  toolCatalogStatus: string;
  agentFiles: AgentWorkspaceFile[];
  credentials: CredentialRef[];
  availableTools: ToolCatalog | null;
  adminStatus: string;
  catalogStatus: string;
  traceRows: TraceRow[];
  activeConversationId: string;
  conversations: StudioConversation[];
  messages: ChatMessage[];
  input: string;
  isRunning: boolean;
  agents: AgentSummary[];
  conversationSidebarOpen: boolean;
  onToggleConversationSidebar: () => void;
  onChangeConversationAgent: (agentId: string) => void;
  onEditMessage: (messageId: string, content: string) => void;
  onInputChange: (value: string) => void;
  onNewConversation: () => void;
  onDeleteConversation: (conversationId: string) => void;
  onRegenerate: (messageId: string) => void;
  onRenameConversation: (conversationId: string, title: string) => void;
  onSelectConversation: (conversationId: string) => void;
  onSubmitChat: (event: FormEvent<HTMLFormElement>) => void;
  onCancelChat: () => void;
  onNavigate: (tab: StudioTab) => void;
};

export function HomePage({
  mode,
  settings,
  agentDetail,
  skillCount,
  selectedSkillCount,
  mcpDrafts,
  toolCatalog,
  toolCatalogStatus,
  agentFiles,
  credentials,
  availableTools,
  adminStatus,
  catalogStatus,
  traceRows,
  activeConversationId,
  conversations,
  messages,
  input,
  isRunning,
  agents,
  conversationSidebarOpen,
  onToggleConversationSidebar,
  onChangeConversationAgent,
  onEditMessage,
  onInputChange,
  onNewConversation,
  onDeleteConversation,
  onRegenerate,
  onRenameConversation,
  onSelectConversation,
  onSubmitChat,
  onCancelChat,
  onNavigate,
}: HomePageProps) {
  const [editingMessageId, setEditingMessageId] = useState<string>("");
  const [editingContent, setEditingContent] = useState("");
  const [copiedId, setCopiedId] = useState("");
  const chatLogRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const autoScrollRef = useRef(true);
  const lastScrollTopRef = useRef(0);
  const [showScrollDown, setShowScrollDown] = useState(false);

  const scrollToBottom = useCallback(() => {
    if (chatLogRef.current) {
      chatLogRef.current.scrollTop = chatLogRef.current.scrollHeight;
      autoScrollRef.current = true;
      setShowScrollDown(false);
    }
  }, []);

  useEffect(() => {
    if (!autoScrollRef.current) return;
    const frame = requestAnimationFrame(() => {
      if (autoScrollRef.current && chatLogRef.current) {
        chatLogRef.current.scrollTop = chatLogRef.current.scrollHeight;
      }
    });
    return () => cancelAnimationFrame(frame);
  }, [messages, isRunning]);

  function handleChatScroll() {
    const el = chatLogRef.current;
    if (!el) return;
    const scrollTop = el.scrollTop;
    const atBottom = el.scrollHeight - scrollTop - el.clientHeight < 80;
    // User scrolling up detaches auto-follow immediately, even mid-stream.
    if (scrollTop < lastScrollTopRef.current) {
      autoScrollRef.current = false;
    } else if (atBottom) {
      autoScrollRef.current = true;
    }
    lastScrollTopRef.current = scrollTop;
    setShowScrollDown(!atBottom && messages.length > 3);
  }

  async function copyMessage(message: ChatMessage) {
    await navigator.clipboard.writeText(message.content);
    setCopiedId(message.id);
    setTimeout(() => setCopiedId(""), 2000);
  }

  function startEditing(message: ChatMessage) {
    setEditingMessageId(message.id);
    setEditingContent(message.content);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (input.trim() && !isRunning) {
        const form = event.currentTarget.closest("form");
        if (form) form.requestSubmit();
      }
    }
  }

  function autoGrow(el: HTMLTextAreaElement) {
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  }

  useEffect(() => {
    textareaRef.current?.focus();
  }, [activeConversationId]);

  const quickSuggestions = [
    "用当前 agent 的配置介绍一下你能做什么",
    "列出你可以使用的工具",
    "帮我分析一下当前项目的结构",
  ];

  const enabledMcpCount = mcpDrafts.filter((draft) => draft.enabled).length;
  const toolCount = toolCatalog?.tools.length ?? 0;

  if (mode === "build") {
    return (
      <>
        <section className="section-block">
          <div className="section-title">
            <SlidersHorizontal size={17} />
            <h2>Build workspace</h2>
            <span>{settings.agentId || "main"} configuration health</span>
          </div>
          <StatStrip
            stats={[
              { label: "Agent", value: settings.agentId || "-", hint: agentDetail?.exposed === false ? "hidden" : "exposed" },
              { label: "Skills", value: formatCount(skillCount), hint: `${formatCount(selectedSkillCount)} default` },
              { label: "MCP", value: formatCount(mcpDrafts.length), hint: `${enabledMcpCount} enabled` },
              { label: "Tools", value: formatCount(toolCount), hint: toolCatalogStatus },
              { label: "Files", value: `${agentFiles.filter((file) => file.exists !== false).length}/${agentFiles.length || 3}` },
              { label: "Credentials", value: formatCount(credentials.length) },
              { label: "Available tools", value: formatCount(availableTools?.tools.length ?? 0) },
              { label: "Admin", value: adminStatus },
            ]}
          />
        </section>

        <Card className="panel">
          <Card.Header className="panel-header">
            <div className="panel-title">
              <Braces size={18} />
              <span>Configuration checklist</span>
            </div>
          </Card.Header>
          <Card.Content className="panel-content">
            <div className="breakdown-list config-checklist">
              <button className="suggestion-row" type="button" onClick={() => onNavigate("configure")}>
                <strong>Agent config</strong>
                <span>Model, sandbox, requested tools, spawn boundaries</span>
              </button>
              <button className="suggestion-row" type="button" onClick={() => onNavigate("skills")}>
                <strong>Skills</strong>
                <span>Install/update skills and choose default selected skills</span>
              </button>
              <button className="suggestion-row" type="button" onClick={() => onNavigate("mcp")}>
                <strong>MCP servers</strong>
                <span>Manage transports, enabled state, and credential references</span>
              </button>
              <button className="suggestion-row" type="button" onClick={() => onNavigate("files")}>
                <strong>Source files</strong>
                <span>Edit AGENTS.md, agent.yaml, and mcp.json with sha256 guards</span>
              </button>
            </div>
          </Card.Content>
        </Card>
      </>
    );
  }

  const lastAssistantMessage = [...messages].reverse().find((m) => m.role === "assistant" && m.id !== "welcome");

  return (
    <div className="use-home">
      <section className="section-block use-home-top">
        {catalogStatus !== "ready" ? (
          <Card className="setup-wizard">
            <Card.Content>
              <div className="empty-icon">
                <PlugZap size={27} />
              </div>
              <div>
                <h3>Connect AnyAgent Server</h3>
                <p>Configure the server URL, test the connection, then select an agent before running a session.</p>
              </div>
              <div className="inline-actions">
                <Button size="sm" variant="primary" onPress={() => onNavigate("settings")}>
                  Configure server
                </Button>
                <Button size="sm" variant="secondary" onPress={() => onNavigate("agents")}>
                  Select agent
                </Button>
              </div>
            </Card.Content>
          </Card>
        ) : null}
        <div className="section-title">
          <Activity size={17} />
          <h2>Tracing</h2>
          <span>Last 7 Days</span>
        </div>
        <CompactTable
          className="ds-trace-table"
          columns={[
            { key: "name", header: "Name", render: (r: TraceRow) => <strong className="ds-cell-strong">{r.name}</strong> },
            { key: "latest", header: "Most Recent Run", render: (r: TraceRow) => <span className="ds-cell-mono">{r.latest}</span> },
            { key: "traces", header: "Traces", align: "right", width: "80px", render: (r: TraceRow) => formatCount(r.traces) },
            { key: "errors", header: "Error Rate", align: "right", width: "90px", render: (r: TraceRow) => <span className={`ds-cell-mono ${traceErrorTone(r.errors)}`}>{r.errors}</span> },
            { key: "p50", header: "P50", align: "right", width: "90px", render: (r: TraceRow) => <span className="ds-cell-mono">{r.p50}</span> },
            { key: "p99", header: "P99", align: "right", width: "90px", render: (r: TraceRow) => <span className="ds-cell-mono">{r.p99}</span> },
            { key: "desc", header: "Description", render: (r: TraceRow) => <span className="ds-cell-sub">{r.description}</span> },
          ]}
          rows={traceRows}
          rowKey={(r) => r.name}
        />
      </section>

      <div className={`main-grid chat-grid ${conversationSidebarOpen ? "" : "sidebar-hidden"}`}>
        {/* ── Conversation Sidebar ── */}
        <ConversationSidebar
          conversations={conversations}
          activeConversationId={activeConversationId}
          open={conversationSidebarOpen}
          onSelect={onSelectConversation}
          onNew={onNewConversation}
          onDelete={onDeleteConversation}
          onRename={onRenameConversation}
          onToggle={onToggleConversationSidebar}
        />

        {/* ── Left: Chat Panel ── */}
        <Card className="panel chat-panel">
          <Card.Header className="panel-header chat-header">
            <div className="panel-title">
              {!conversationSidebarOpen && (
                <button className="conversation-sidebar-toggle" onClick={onToggleConversationSidebar}>
                  <PanelLeftOpen size={16} />
                </button>
              )}
              <MessageSquareText size={18} />
              <span>Chat</span>
              <AgentSelector
                agents={agents}
                currentAgentId={conversations.find((c) => c.id === activeConversationId)?.agentId || settings.agentId}
                onChangeAgent={onChangeConversationAgent}
              />
              {settings.model ? (
                <span className="chat-model-badge">{settings.model}</span>
              ) : null}
            </div>
            <div className="editor-actions chat-actions">
              {isRunning ? (
                <Button size="sm" variant="secondary" onPress={onCancelChat}>
                  <Square size={13} />
                  Stop
                </Button>
              ) : null}
              <Button size="sm" variant="secondary" onPress={onNewConversation}>
                <Plus size={15} />
                New
              </Button>
              <Chip size="sm" variant="soft" color={isRunning ? "warning" : "success"}>
                {isRunning ? "running" : "ready"}
              </Chip>
            </div>
          </Card.Header>
          <Card.Content className="panel-content chat-content">
            {/* Messages */}
            <div className="chat-log" ref={chatLogRef} onScroll={handleChatScroll}>
              {messages.length === 0 ? (
                <div className="chat-empty">
                  <div className="chat-empty-icon">
                    <Sparkles size={32} />
                  </div>
                  <h3>Start a conversation</h3>
                  <p>with <strong>{settings.agentId || "the agent"}</strong></p>
                  <div className="chat-suggestions">
                    {quickSuggestions.map((suggestion) => (
                      <button
                        key={suggestion}
                        type="button"
                        className="chat-suggestion-btn"
                        onClick={() => {
                          onInputChange(suggestion);
                          textareaRef.current?.focus();
                        }}
                      >
                        {suggestion}
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                messages.map((message, idx) => {
                  const isLastAssistant = message.role === "assistant" && idx === messages.length - 1;
                  const isStreamingMsg = isLastAssistant && isRunning;
                  return (
                    <article className={`message ${message.role}`} key={message.id}>
                      <div className="message-avatar">
                        {message.role === "user" ? <User size={15} /> : <Bot size={15} />}
                      </div>
                      <div className="message-body">
                        <div className="message-meta">
                          <span className="message-role">
                            {message.role === "user" ? "You" : settings.agentId || "Agent"}
                          </span>
                          <div className="message-actions">
                            <button
                              type="button"
                              title={copiedId === message.id ? "Copied" : "Copy"}
                              onClick={() => void copyMessage(message)}
                            >
                              {copiedId === message.id ? <Check size={14} /> : <Copy size={14} />}
                            </button>
                            {message.role === "user" ? (
                              <button type="button" title="Edit and resend" onClick={() => startEditing(message)}>
                                <Pencil size={14} />
                              </button>
                            ) : message.id !== "welcome" ? (
                              <button type="button" title="Regenerate" onClick={() => onRegenerate(message.id)}>
                                <RefreshCw size={14} />
                              </button>
                            ) : null}
                          </div>
                        </div>
                        {editingMessageId !== message.id && message.thinking ? (
                          <ThinkingBlock content={message.thinking} isStreaming={isStreamingMsg && !message.content} />
                        ) : null}
                        {editingMessageId === message.id ? (
                          <div className="message-editor">
                            <textarea
                              aria-label="Edit message"
                              rows={3}
                              value={editingContent}
                              onChange={(event) => setEditingContent(event.target.value)}
                            />
                            <div className="inline-actions">
                              <Button
                                size="sm"
                                variant="primary"
                                onPress={() => {
                                  onEditMessage(message.id, editingContent);
                                  setEditingMessageId("");
                                }}
                              >
                                Send edited
                              </Button>
                              <Button size="sm" variant="secondary" onPress={() => setEditingMessageId("")}>
                                Cancel
                              </Button>
                            </div>
                          </div>
                        ) : message.content ? (
                          message.role === "assistant" ? (
                            <MarkdownMessage content={message.content} isStreaming={isStreamingMsg} />
                          ) : (
                            <p className="message-text">{message.content}</p>
                          )
                        ) : isStreamingMsg && !message.thinking ? (
                          <div className="streaming-indicator">
                            <span className="streaming-dot" />
                            <span className="streaming-dot" />
                            <span className="streaming-dot" />
                            <span className="streaming-label">Thinking...</span>
                          </div>
                        ) : null}
                        {/* Tool calls */}
                        {message.toolCalls?.length ? (
                          <div className="tool-calls">
                            {message.toolCalls.map((tc) => (
                              <ToolCallCard key={tc.id} toolCall={tc} />
                            ))}
                          </div>
                        ) : null}
                      </div>
                    </article>
                  );
                })
              )}
            </div>

            {/* Scroll to bottom button */}
            {showScrollDown ? (
              <button type="button" className="scroll-to-bottom" onClick={scrollToBottom} title="Scroll to bottom">
                <ArrowDown size={16} />
              </button>
            ) : null}

            {/* Composer */}
            <form className="composer" onSubmit={onSubmitChat}>
              <div className="composer-input-wrap">
                <textarea
                  ref={textareaRef}
                  rows={1}
                  value={input}
                  onChange={(event) => {
                    onInputChange(event.target.value);
                    autoGrow(event.target);
                  }}
                  onKeyDown={handleKeyDown}
                  onFocus={(event) => autoGrow(event.target)}
                  placeholder={`Message ${settings.agentId || "agent"}...`}
                  aria-label="Message"
                />
              </div>
              <button
                type="submit"
                disabled={isRunning || !input.trim()}
                className="composer-send-btn"
                title="Send message"
              >
                <Send size={16} />
              </button>
            </form>
            <span className="composer-hint">Enter to send · Shift+Enter for newline</span>
          </Card.Content>
        </Card>

        {/* ── Right: Session Detail Panel ── */}
        <aside className="detail-panel">
          {/* Agent Context Card */}
          <Card className="panel detail-card">
            <Card.Header className="panel-header">
              <div className="panel-title">
                <Zap size={16} />
                <span>Agent Context</span>
              </div>
            </Card.Header>
            <Card.Content className="panel-content">
              <div className="detail-grid">
                <DetailRow label="Agent ID" value={settings.agentId || "—"} />
                <DetailRow label="Model" value={settings.model || agentDetail?.model_default || "—"} />
                <DetailRow
                  label="Provider"
                  value={agentDetail?.model_provider || settings.model?.split("/")[0] || "—"}
                />
                <DetailRow label="Sandbox" value={agentDetail?.sandbox_mode || "—"} />
                <DetailRow
                  label="Exposed"
                  value={agentDetail?.exposed === false ? "Hidden" : "Public"}
                />
              </div>
            </Card.Content>
          </Card>

          {/* Context Summary Card */}
          <Card className="panel detail-card">
            <Card.Header className="panel-header">
              <div className="panel-title">
                <PackagePlus size={16} />
                <span>Context Summary</span>
              </div>
            </Card.Header>
            <Card.Content className="panel-content">
              <div className="detail-grid">
                <DetailRow
                  label="Skills"
                  value={`${selectedSkillCount} selected / ${skillCount} total`}
                />
                <DetailRow
                  label="MCP Servers"
                  value={`${enabledMcpCount} enabled / ${mcpDrafts.length} configured`}
                />
                <DetailRow label="Requested Tools" value={formatCount(toolCount)} />
                <DetailRow
                  label="Prompt"
                  value={agentDetail?.agents_md?.sha256 ? shortHash(agentDetail.agents_md.sha256) : "—"}
                  mono
                />
                <DetailRow label="Credentials" value={formatCount(credentials.length)} />
                <DetailRow label="Files" value={formatCount(agentFiles.length)} />
              </div>
            </Card.Content>
          </Card>

          {/* Conversation Stats Card */}
          <Card className="panel detail-card">
            <Card.Header className="panel-header">
              <div className="panel-title">
                <Activity size={16} />
                <span>Session Stats</span>
              </div>
            </Card.Header>
            <Card.Content className="panel-content">
              <div className="detail-grid">
                <DetailRow label="Conversations" value={formatCount(conversations.length)} />
                <DetailRow label="Messages" value={formatCount(messages.length)} />
                <DetailRow
                  label="Last Response"
                  value={
                    lastAssistantMessage?.content
                      ? `${lastAssistantMessage.content.length} chars`
                      : "—"
                  }
                />
                <DetailRow label="Status" value={isRunning ? "Running" : "Idle"} dot={isRunning ? "running" : "idle"} />
              </div>
            </Card.Content>
          </Card>
        </aside>
      </div>
    </div>
  );
}

function ToolCallCard({ toolCall }: { toolCall: ToolCallItem }) {
  const [expanded, setExpanded] = useState(false);
  const KindIcon = toolCall.kind === "mcp" ? Puzzle : toolCall.kind === "command" ? Terminal : Wrench;
  const statusClass = toolCall.status === "success" ? "tc-success" : toolCall.status === "failed" ? "tc-failed" : "tc-running";

  return (
    <div className={`tool-call-card ${statusClass}`}>
      <button type="button" className="tc-header" onClick={() => setExpanded((v) => !v)}>
        <KindIcon size={14} />
        <span className="tc-name">{toolCall.toolName}</span>
        <span className="tc-kind">{toolCall.kind}</span>
        {toolCall.durationMs ? <span className="tc-duration">{toolCall.durationMs}ms</span> : null}
        <span className={`tc-status ${statusClass}`}>
          {toolCall.status === "running" ? "⟳" : toolCall.status === "success" ? "✓" : "✗"}
        </span>
        {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
      </button>
      {expanded ? (
        <div className="tc-body">
          {toolCall.arguments ? (
            <div className="tc-section">
              <span className="tc-section-label">Arguments</span>
              <pre className="tc-pre">{toolCall.arguments}</pre>
            </div>
          ) : null}
          {toolCall.output ? (
            <div className="tc-section">
              <span className="tc-section-label">Output</span>
              <pre className="tc-pre">{toolCall.output}</pre>
            </div>
          ) : null}
          {toolCall.error ? (
            <div className="tc-section tc-error-section">
              <span className="tc-section-label">Error</span>
              <pre className="tc-pre">{toolCall.error}</pre>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function ThinkingBlock({ content, isStreaming }: { content: string; isStreaming: boolean }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className={`thinking-block ${isStreaming ? "thinking-streaming" : ""}`}>
      <button type="button" className="thinking-header" onClick={() => setExpanded((v) => !v)}>
        <Sparkles size={13} className="thinking-icon" />
        <span className="thinking-label">{isStreaming ? "Thinking..." : "Thinking"}</span>
        <span className="thinking-length">{content.length > 100 ? `${Math.ceil(content.length / 4)} tokens` : ""}</span>
        {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
      </button>
      {expanded ? (
        <div className="thinking-content">
          <MarkdownMessage content={content} isStreaming={isStreaming} />
        </div>
      ) : null}
    </div>
  );
}

function DetailRow({ label, value, mono, dot }: { label: string; value: string; mono?: boolean; dot?: "running" | "idle" }) {
  return (
    <div className="detail-row">
      <span className="detail-label">{label}</span>
      <span className={`detail-value ${mono ? "detail-mono" : ""}`}>
        {dot ? <span className={`detail-status-dot ${dot === "running" ? "running" : ""}`} /> : null}
        {value}
      </span>
    </div>
  );
}
