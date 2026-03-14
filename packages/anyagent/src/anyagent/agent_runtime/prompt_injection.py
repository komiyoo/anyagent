from __future__ import annotations

from anyagent.agent_packs import AgentPack
from anyagent.agent_runtime.prompt_envelope import build_agents_md_fragment
from anyagent.protocol.context_fragments import render_context_fragment


def build_agents_md_injection_text(pack: AgentPack) -> str:
    """Build structured AGENTS fragment text from one Agent Pack."""

    return render_context_fragment(build_agents_md_fragment(pack))
