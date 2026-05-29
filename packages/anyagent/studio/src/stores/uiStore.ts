import { create } from "zustand";
import { persist } from "zustand/middleware";

export type StudioTheme = "light" | "dark";

type UiStore = {
  sidebarCollapsed: boolean;
  conversationSidebarOpen: boolean;
  theme: StudioTheme;
  setSidebarCollapsed: (value: boolean | ((current: boolean) => boolean)) => void;
  setConversationSidebarOpen: (value: boolean | ((current: boolean) => boolean)) => void;
  toggleTheme: () => void;
};

export const useUiStore = create<UiStore>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      conversationSidebarOpen: true,
      theme: "light",
      setSidebarCollapsed: (value) =>
        set((state) => ({
          sidebarCollapsed: typeof value === "function" ? value(state.sidebarCollapsed) : value,
        })),
      setConversationSidebarOpen: (value) =>
        set((state) => ({
          conversationSidebarOpen: typeof value === "function" ? value(state.conversationSidebarOpen) : value,
        })),
      toggleTheme: () => set((state) => ({ theme: state.theme === "light" ? "dark" : "light" })),
    }),
    {
      name: "anyagent.studio.ui.v1",
    },
  ),
);
