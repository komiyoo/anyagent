import { lazy } from "react";
import type { ComponentType, LazyExoticComponent } from "react";
import { StudioTab } from "../navigation";

type LazyStudioPage = LazyExoticComponent<ComponentType<Record<string, never>>> | ComponentType<any>;

function lazyPage<T extends Record<string, unknown>, K extends keyof T & string>(loader: () => Promise<T>, exportName: K) {
  return {
    Component: lazy(() => loader().then((module) => ({ default: module[exportName] as ComponentType<any> }))) as ComponentType<any>,
    preload: loader,
  };
}

const pages = {
  agents: lazyPage(() => import("./AgentsPage"), "AgentsPage"),
  audit: lazyPage(() => import("./AuditPage"), "AuditPage"),
  configure: lazyPage(() => import("./ConfigurePage"), "ConfigurePage"),
  credentials: lazyPage(() => import("./CredentialsPage"), "CredentialsPage"),
  debug: lazyPage(() => import("./DebugPage"), "DebugPage"),
  evaluations: lazyPage(() => import("./EvaluationsPage"), "EvaluationsPage"),
  files: lazyPage(() => import("./FilesPage"), "FilesPage"),
  home: lazyPage(() => import("./HomePage"), "HomePage"),
  mcp: lazyPage(() => import("./McpPage"), "McpPage"),
  observability: lazyPage(() => import("./ObservabilityPage"), "ObservabilityPage"),
  prompts: lazyPage(() => import("./PromptsPage"), "PromptsPage"),
  sessions: lazyPage(() => import("./SessionsPage"), "SessionsPage"),
  settings: lazyPage(() => import("./SettingsPage"), "SettingsPage"),
  skills: lazyPage(() => import("./SkillsPage"), "SkillsPage"),
  tools: lazyPage(() => import("./ToolsPage"), "ToolsPage"),
} satisfies Record<StudioTab, { Component: LazyStudioPage; preload: () => Promise<unknown> }>;

export const AgentsPage = pages.agents.Component;
export const AuditPage = pages.audit.Component;
export const ConfigurePage = pages.configure.Component;
export const CredentialsPage = pages.credentials.Component;
export const DebugPage = pages.debug.Component;
export const EvaluationsPage = pages.evaluations.Component;
export const FilesPage = pages.files.Component;
export const HomePage = pages.home.Component;
export const McpPage = pages.mcp.Component;
export const ObservabilityPage = pages.observability.Component;
export const PromptsPage = pages.prompts.Component;
export const SessionsPage = pages.sessions.Component;
export const SettingsPage = pages.settings.Component;
export const SkillsPage = pages.skills.Component;
export const ToolsPage = pages.tools.Component;

export function preloadStudioPage(tab: StudioTab) {
  void pages[tab].preload();
}
