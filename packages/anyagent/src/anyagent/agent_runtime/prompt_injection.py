from __future__ import annotations

from anyagent.agent_packs import AgentPack


def build_agents_md_injection_text(pack: AgentPack) -> str:
    """Build developer-message injection text from one Agent Pack."""

    body = (pack.agents_md_text or "").rstrip()
    return "\n".join(
        [
            "[anyagent Agent Pack]",
            f"agent_id: {pack.agent_id}",
            f"path: {pack.agents_md_path}",
            f"sha256: {pack.agents_md_sha256}",
            "",
            "[AGENTS_BODY]",
            body,
        ]
    ).rstrip()
