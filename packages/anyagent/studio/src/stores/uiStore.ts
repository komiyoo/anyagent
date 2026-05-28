import { create } from "zustand";
import { persist } from "zustand/middleware";

export type StudioTheme = "light" | "dark";

type UiStore = {
  sidebarCollapsed: boolean;
  theme: StudioTheme;
  setSidebarCollapsed: (value: boolean | ((current: boolean) => boolean)) => void;
  toggleTheme: () => void;
};

export const useUiStore = create<UiStore>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      theme: "light",
      setSidebarCollapsed: (value) =>
        set((state) => ({
          sidebarCollapsed: typeof value === "function" ? value(state.sidebarCollapsed) : value,
        })),
      toggleTheme: () => set((state) => ({ theme: state.theme === "light" ? "dark" : "light" })),
    }),
    {
      name: "anyagent.studio.ui.v1",
    },
  ),
);
