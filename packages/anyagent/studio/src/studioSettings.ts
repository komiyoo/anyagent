import { StudioSettings } from "./anyagentClient";

export const settingsStorageKey = "anyagent.studio.settings.v1";

export type ConnectionDraft = Pick<StudioSettings, "baseUrl" | "apiKey" | "adminKey">;

export const envSettings: StudioSettings = {
  baseUrl: import.meta.env.VITE_ANYAGENT_BASE_URL ?? window.location.origin,
  apiKey: import.meta.env.VITE_ANYAGENT_API_KEY ?? "anyagent-dev-key",
  adminKey: import.meta.env.VITE_ANYAGENT_ADMIN_KEY ?? import.meta.env.VITE_ANYAGENT_API_KEY ?? "anyagent-dev-key",
  model: import.meta.env.VITE_ANYAGENT_MODEL ?? "gpt-5.5",
  agentId: import.meta.env.VITE_ANYAGENT_AGENT_ID ?? "main",
  sessionKey: `studio-${new Date().toISOString().slice(0, 10)}`,
};

export const normalizeBaseUrl = (value: string) => {
  const trimmed = value.trim();
  return trimmed ? trimmed.replace(/\/+$/, "") : envSettings.baseUrl;
};

export const normalizeSettings = (settings: StudioSettings): StudioSettings => ({
  ...settings,
  baseUrl: normalizeBaseUrl(settings.baseUrl),
  apiKey: settings.apiKey.trim(),
  adminKey: settings.adminKey.trim(),
  model: settings.model.trim() || envSettings.model,
  agentId: settings.agentId.trim() || envSettings.agentId,
  sessionKey: settings.sessionKey.trim() || envSettings.sessionKey,
});

export function readStoredSettings(): StudioSettings {
  try {
    const raw = window.localStorage.getItem(settingsStorageKey);
    if (!raw) {
      return envSettings;
    }
    const parsed = JSON.parse(raw) as Partial<StudioSettings> & { version?: number };
    return normalizeSettings({
      ...envSettings,
      baseUrl: typeof parsed.baseUrl === "string" ? parsed.baseUrl : envSettings.baseUrl,
      apiKey: typeof parsed.apiKey === "string" ? parsed.apiKey : envSettings.apiKey,
      adminKey: typeof parsed.adminKey === "string" ? parsed.adminKey : envSettings.adminKey,
      model: typeof parsed.model === "string" ? parsed.model : envSettings.model,
      agentId: typeof parsed.agentId === "string" ? parsed.agentId : envSettings.agentId,
      sessionKey: typeof parsed.sessionKey === "string" ? parsed.sessionKey : envSettings.sessionKey,
    });
  } catch {
    return envSettings;
  }
}

export function writeStoredSettings(settings: StudioSettings) {
  window.localStorage.setItem(settingsStorageKey, JSON.stringify({ version: 1, ...normalizeSettings(settings) }));
}

export function clearStoredSettings() {
  window.localStorage.removeItem(settingsStorageKey);
}
