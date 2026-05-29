import { create } from "zustand";
import { ChatMessage, StudioDebugEvent } from "../anyagentClient";

export type StudioConversation = {
  id: string;
  title: string;
  messages: ChatMessage[];
  updatedAt: number;
};

const STORAGE_KEY = "anyagent.studio.chat.v1";

const welcomeMessage: ChatMessage = {
  id: "welcome",
  role: "assistant",
  content: "AnyAgent Studio is ready. Pick an agent, inspect its pack, then run a client session.",
};

function newId(prefix: string) {
  return `${prefix}-${crypto.randomUUID()}`;
}

function defaultConversation(): StudioConversation {
  return {
    id: newId("conversation"),
    title: "New conversation",
    messages: [welcomeMessage],
    updatedAt: Date.now(),
  };
}

function titleFromMessages(messages: ChatMessage[]) {
  const firstUserMessage = messages.find((message) => message.role === "user" && message.content.trim());
  if (!firstUserMessage) {
    return "New conversation";
  }
  return firstUserMessage.content.trim().replace(/\s+/g, " ").slice(0, 48);
}

type PersistedChatState = {
  activeConversationId: string;
  conversations: StudioConversation[];
};

function readPersistedChat(): PersistedChatState {
  if (typeof window === "undefined") {
    const conversation = defaultConversation();
    return { activeConversationId: conversation.id, conversations: [conversation] };
  }
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      const conversation = defaultConversation();
      return { activeConversationId: conversation.id, conversations: [conversation] };
    }
    const parsed = JSON.parse(raw) as Partial<PersistedChatState>;
    const conversations = Array.isArray(parsed.conversations) && parsed.conversations.length ? parsed.conversations : [defaultConversation()];
    const activeConversationId = parsed.activeConversationId && conversations.some((item) => item.id === parsed.activeConversationId)
      ? parsed.activeConversationId
      : conversations[0].id;
    return { activeConversationId, conversations };
  } catch {
    const conversation = defaultConversation();
    return { activeConversationId: conversation.id, conversations: [conversation] };
  }
}

function persistChat(state: PersistedChatState) {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

type ChatStore = {
  activeConversationId: string;
  activeResponseId: string;
  conversations: StudioConversation[];
  input: string;
  isRunning: boolean;
  messages: ChatMessage[];
  promptBundle: Record<string, unknown> | null;
  stageEvents: StudioDebugEvent[];
  streamEvents: StudioDebugEvent[];
  appendMessage: (message: ChatMessage) => void;
  deleteConversation: (id: string) => void;
  newConversation: () => void;
  renameConversation: (id: string, title: string) => void;
  replaceMessage: (id: string, content: string) => void;
  selectConversation: (id: string) => void;
  setActiveResponseId: (value: string) => void;
  setInput: (value: string) => void;
  setIsRunning: (value: boolean) => void;
  setMessages: (value: ChatMessage[] | ((current: ChatMessage[]) => ChatMessage[])) => void;
  setPromptBundle: (value: Record<string, unknown> | null) => void;
  setStageEvents: (value: StudioDebugEvent[] | ((current: StudioDebugEvent[]) => StudioDebugEvent[])) => void;
  setStreamEvents: (value: StudioDebugEvent[] | ((current: StudioDebugEvent[]) => StudioDebugEvent[])) => void;
};

const initial = readPersistedChat();
const initialMessages = initial.conversations.find((item) => item.id === initial.activeConversationId)?.messages ?? [welcomeMessage];

export const useChatStore = create<ChatStore>((set, get) => {
  function commitMessages(nextMessages: ChatMessage[]) {
    const conversations = get().conversations.map((conversation) =>
      conversation.id === get().activeConversationId
        ? {
            ...conversation,
            messages: nextMessages,
            title: titleFromMessages(nextMessages),
            updatedAt: Date.now(),
          }
        : conversation,
    );
    persistChat({ activeConversationId: get().activeConversationId, conversations });
    set({ conversations, messages: nextMessages });
  }

  return {
    activeConversationId: initial.activeConversationId,
    activeResponseId: "",
    conversations: initial.conversations,
    input: "用当前 agent 的配置介绍一下你能做什么。",
    isRunning: false,
    messages: initialMessages,
    promptBundle: null,
    stageEvents: [],
    streamEvents: [],
    appendMessage: (message) => commitMessages([...get().messages, message]),
    deleteConversation: (id) => {
      const conversations = get().conversations.filter((conversation) => conversation.id !== id);
      if (!conversations.length) {
        const conversation = defaultConversation();
        conversations.push(conversation);
      }
      const activeConversationId = conversations.some((conversation) => conversation.id === get().activeConversationId)
        ? get().activeConversationId
        : conversations[0].id;
      const activeConversation = conversations.find((conversation) => conversation.id === activeConversationId)!;
      persistChat({ activeConversationId, conversations });
      set({
        activeConversationId,
        activeResponseId: "",
        conversations,
        input: "",
        messages: activeConversation.messages,
        promptBundle: null,
        stageEvents: [],
        streamEvents: [],
      });
    },
    newConversation: () => {
      const conversation = defaultConversation();
      const conversations = [conversation, ...get().conversations];
      persistChat({ activeConversationId: conversation.id, conversations });
      set({
        activeConversationId: conversation.id,
        activeResponseId: "",
        conversations,
        input: "用当前 agent 的配置介绍一下你能做什么。",
        messages: conversation.messages,
        promptBundle: null,
        stageEvents: [],
        streamEvents: [],
      });
    },
    renameConversation: (id, title) =>
      set((state) => {
        const conversations = state.conversations.map((conversation) =>
          conversation.id === id ? { ...conversation, title: title.trim() || "New conversation", updatedAt: Date.now() } : conversation,
        );
        persistChat({ activeConversationId: state.activeConversationId, conversations });
        return { conversations };
      }),
    replaceMessage: (id, content) => commitMessages(get().messages.map((message) => (message.id === id ? { ...message, content } : message))),
    selectConversation: (id) => {
      const conversation = get().conversations.find((item) => item.id === id);
      if (!conversation) {
        return;
      }
      persistChat({ activeConversationId: id, conversations: get().conversations });
      set({
        activeConversationId: id,
        activeResponseId: "",
        input: "",
        messages: conversation.messages,
        promptBundle: null,
        stageEvents: [],
        streamEvents: [],
      });
    },
    setActiveResponseId: (value) => set({ activeResponseId: value }),
    setInput: (value) => set({ input: value }),
    setIsRunning: (value) => set({ isRunning: value }),
    setMessages: (value) => {
      const nextMessages = typeof value === "function" ? value(get().messages) : value;
      commitMessages(nextMessages);
    },
    setPromptBundle: (value) => set({ promptBundle: value }),
    setStageEvents: (value) =>
      set((state) => ({
        stageEvents: typeof value === "function" ? value(state.stageEvents) : value,
      })),
    setStreamEvents: (value) =>
      set((state) => ({
        streamEvents: typeof value === "function" ? value(state.streamEvents) : value,
      })),
  };
});
