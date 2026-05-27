import { McpServerDraft } from "./anyagentClient";

export const sampleMcpDrafts: McpServerDraft[] = [
  {
    name: "amap",
    enabled: true,
    transport: "streamable_http",
    url: "http://127.0.0.1:8000/mcp",
    command: "",
    credentialId: "cred_amap",
  },
];

export const sampleSkillMarkdown = `---
name: sales-discovery
description: Helps qualify customer discovery notes.
metadata:
  short-description: Sales discovery helper
---

Use this skill when the user is preparing, summarizing, or following up on a customer discovery conversation.
`;
