import { create } from "zustand";
import { AdminStatus, StudioSettings } from "../anyagentClient";
import {
  clearStoredSettings,
  ConnectionDraft,
  envSettings,
  normalizeSettings,
  readStoredSettings,
  writeStoredSettings,
} from "../studioSettings";

const initialSettings = readStoredSettings();

type SettingsStore = {
  adminStatus: string;
  connectionDraft: ConnectionDraft;
  connectionTestStatus: string;
  credentialCapabilities: AdminStatus | null;
  serverHealth: AdminStatus | null;
  settings: StudioSettings;
  settingsStatus: string;
  storageHealth: AdminStatus | null;
  applyConnectionDraft: () => void;
  resetStoredSettings: () => void;
  setAdminHealth: (payload: {
    adminStatus: string;
    credentialCapabilities: AdminStatus | null;
    serverHealth: AdminStatus | null;
    storageHealth: AdminStatus | null;
  }) => void;
  setAdminStatus: (value: string) => void;
  setConnectionTestStatus: (value: string) => void;
  updateConnectionDraft: <K extends keyof ConnectionDraft>(key: K, value: ConnectionDraft[K]) => void;
  updateSettings: <K extends keyof StudioSettings>(key: K, value: StudioSettings[K]) => void;
};

export const useSettingsStore = create<SettingsStore>((set, get) => ({
  adminStatus: "Not loaded",
  connectionDraft: {
    baseUrl: initialSettings.baseUrl,
    apiKey: initialSettings.apiKey,
    adminKey: initialSettings.adminKey,
  },
  connectionTestStatus: "Not tested",
  credentialCapabilities: null,
  serverHealth: null,
  settings: initialSettings,
  settingsStatus: "Loaded",
  storageHealth: null,
  applyConnectionDraft: () =>
    set((state) => {
      const next = normalizeSettings({ ...state.settings, ...state.connectionDraft });
      writeStoredSettings(next);
      return {
        connectionDraft: { baseUrl: next.baseUrl, apiKey: next.apiKey, adminKey: next.adminKey },
        settings: next,
        settingsStatus: "Connection applied and saved",
      };
    }),
  resetStoredSettings: () => {
    clearStoredSettings();
    const next = normalizeSettings(envSettings);
    set({
      connectionDraft: { baseUrl: next.baseUrl, apiKey: next.apiKey, adminKey: next.adminKey },
      connectionTestStatus: "Not tested",
      settings: next,
      settingsStatus: "Reset to environment defaults",
    });
  },
  setAdminHealth: (payload) => set(payload),
  setAdminStatus: (value) => set({ adminStatus: value }),
  setConnectionTestStatus: (value) => set({ connectionTestStatus: value }),
  updateConnectionDraft: (key, value) =>
    set((state) => ({
      connectionDraft: { ...state.connectionDraft, [key]: value },
      connectionTestStatus: "Not tested",
      settingsStatus: "Unsaved connection changes",
    })),
  updateSettings: (key, value) => {
    const next = normalizeSettings({ ...get().settings, [key]: value });
    writeStoredSettings(next);
    set({ settings: next, settingsStatus: "Saved" });
  },
}));
