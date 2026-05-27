import {
  BarChart3,
  Bot,
  Bug,
  Code2,
  Database,
  FileText,
  FlaskConical,
  Home,
  KeyRound,
  MessageSquareText,
  PackagePlus,
  Puzzle,
  Settings,
  SlidersHorizontal,
  Wrench,
} from "lucide-react";
import { ForwardRefExoticComponent, RefAttributes } from "react";
import { LucideProps } from "lucide-react";

export type StudioMode = "use" | "build";

export type StudioTab =
  | "home"
  | "agents"
  | "sessions"
  | "observability"
  | "evaluations"
  | "prompts"
  | "settings"
  | "configure"
  | "skills"
  | "mcp"
  | "tools"
  | "credentials"
  | "debug"
  | "files";

export type StudioSection = "chat" | "observability" | "debug" | "configure" | "skills" | "mcp" | "tools" | "files";

export type NavItem = {
  icon: ForwardRefExoticComponent<Omit<LucideProps, "ref"> & RefAttributes<SVGSVGElement>>;
  label: string;
  target: StudioTab;
  shortcut?: string;
  count?: string;
};

export const navGroupsByMode: Record<StudioMode, Array<{ label: string; items: NavItem[] }>> = {
  use: [
    {
      label: "Application",
      items: [
        { icon: Home, label: "Home", target: "home" },
        { icon: Bot, label: "Agents", target: "agents" },
        { icon: MessageSquareText, label: "Sessions", target: "sessions" },
        { icon: BarChart3, label: "Observability", target: "observability", count: "0" },
      ],
    },
    {
      label: "Improve",
      items: [
        { icon: Database, label: "Evaluations", target: "evaluations" },
        { icon: FlaskConical, label: "Prompts", target: "prompts" },
      ],
    },
    {
      label: "Workspace",
      items: [{ icon: Settings, label: "Settings", target: "settings" }],
    },
  ],
  build: [
    {
      label: "Build",
      items: [
        { icon: Home, label: "Home", target: "home" },
        { icon: Bot, label: "Agents", target: "agents" },
        { icon: SlidersHorizontal, label: "Configure", target: "configure" },
        { icon: PackagePlus, label: "Skills", target: "skills" },
      ],
    },
    {
      label: "Capabilities",
      items: [
        { icon: Puzzle, label: "MCP", target: "mcp" },
        { icon: Wrench, label: "Tools", target: "tools" },
        { icon: KeyRound, label: "Credentials", target: "credentials" },
      ],
    },
    {
      label: "Debug",
      items: [
        { icon: Bug, label: "Debug", target: "debug" },
        { icon: FileText, label: "Files", target: "files" },
        { icon: Code2, label: "Settings", target: "settings" },
      ],
    },
  ],
};

export function sectionForTab(tab: StudioTab): StudioSection {
  if (tab === "observability" || tab === "sessions" || tab === "evaluations") {
    return "observability";
  }
  if (tab === "debug" || tab === "prompts") {
    return "debug";
  }
  if (tab === "skills") {
    return "skills";
  }
  if (tab === "mcp") {
    return "mcp";
  }
  if (tab === "tools") {
    return "tools";
  }
  if (tab === "files") {
    return "files";
  }
  if (tab === "configure" || tab === "settings" || tab === "credentials") {
    return "configure";
  }
  return "chat";
}

export function titleForTab(tab: StudioTab): string {
  const titles: Record<StudioTab, string> = {
    home: "Home",
    agents: "Agents",
    sessions: "Sessions",
    observability: "Observability",
    evaluations: "Evaluations",
    prompts: "Prompts",
    settings: "Settings",
    configure: "Configure",
    skills: "Skills",
    mcp: "MCP",
    tools: "Tools",
    credentials: "Credentials",
    debug: "Debug",
    files: "Files",
  };
  return titles[tab];
}

export function subtitleForTab(tab: StudioTab, mode: StudioMode): string {
  if (mode === "build") {
    const buildSubtitles: Partial<Record<StudioTab, string>> = {
      home: "Review build health and jump into agent configuration work",
      agents: "Create, select, and manage agent packs",
      settings: "Inspect server management, health, storage, and credential capabilities",
    };
    if (buildSubtitles[tab]) {
      return buildSubtitles[tab];
    }
  }
  const subtitles: Record<StudioTab, string> = {
    home: "Run the selected agent and inspect the live client session",
    agents: "Choose an exposed workspace agent for use",
    sessions: "Review response runs for the current agent and session",
    observability: "Analyze telemetry, tools, traces, tokens, and errors",
    evaluations: "Promote high-value runs into evaluation seeds",
    prompts: "Preview prompt assembly and inspect context fragments",
    settings: "Manage personal Studio connection and browser-local defaults",
    configure: "Edit agent pack configuration and source files",
    skills: "Install, update, enable, and default-select skills",
    mcp: "Edit MCP server drafts and write mcp.json",
    tools: "Inspect effective and available tool catalogs",
    credentials: "Create and revoke Credential Vault references",
    debug: "Replay stage events and inspect low-level run payloads",
    files: "Edit agent pack source files",
  };
  return subtitles[tab];
}
