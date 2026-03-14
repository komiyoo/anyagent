from __future__ import annotations

import html
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ContextFragmentKind = Literal["agents_instructions", "skill", "environment_context", "mcp_server_ref", "tool_catalog_delta"]
ContextFragmentCacheClass = Literal["stable_prefix", "contextual", "dynamic"]
ContextFragmentRole = Literal["developer", "system"]
_AGENTS_PREFIX = "# AGENTS.md instructions for "
_SKILL_OPEN_TAG = "<skill>"
_SKILL_CLOSE_TAG = "</skill>"
_ENVIRONMENT_OPEN_TAG = "<environment_context>"
_ENVIRONMENT_CLOSE_TAG = "</environment_context>"


class ContextFragment(BaseModel):
    """
    Structured contextual fragment that can be rendered into model-visible text.

    v1 focuses on a minimal common contract for AGENTS / skill injection so the
    runtime can move away from ad-hoc prompt string assembly.
    """

    model_config = ConfigDict(extra="forbid")

    kind: ContextFragmentKind
    role: ContextFragmentRole = "developer"
    cache_class: ContextFragmentCacheClass = "contextual"
    label: str | None = None
    stable_id: str | None = None
    source_path: str | None = None
    source_hash: str | None = None
    scope: str | None = None
    body: str = Field(default="")
    metadata: dict[str, str] = Field(default_factory=dict)


def render_context_fragment(fragment: ContextFragment) -> str:
    if fragment.kind == "agents_instructions":
        return _render_agents_fragment(fragment)
    if fragment.kind == "skill":
        return _render_skill_fragment(fragment)
    return fragment.body.rstrip()


def is_context_fragment_text(text: str) -> bool:
    if not isinstance(text, str):
        return False
    stripped = text.strip()
    return (
        stripped.startswith(_AGENTS_PREFIX)
        or (stripped.startswith(_SKILL_OPEN_TAG) and stripped.endswith(_SKILL_CLOSE_TAG))
        or (stripped.startswith(_ENVIRONMENT_OPEN_TAG) and stripped.endswith(_ENVIRONMENT_CLOSE_TAG))
    )


def _render_agents_fragment(fragment: ContextFragment) -> str:
    label = fragment.label or "project"
    meta_lines = _render_meta_lines(fragment=fragment, include_stable_id=False)
    body = (fragment.body or "").rstrip()
    lines = [f"# AGENTS.md instructions for {label}"]
    if meta_lines:
        lines.extend(["", "<INSTRUCTIONS_META>", *meta_lines, "</INSTRUCTIONS_META>"])
    lines.extend(["", "<INSTRUCTIONS>", body, "</INSTRUCTIONS>"])
    return "\n".join(lines).rstrip()


def _render_skill_fragment(fragment: ContextFragment) -> str:
    body = (fragment.body or "").rstrip()
    lines = ["<skill>", *_render_meta_lines(fragment=fragment, include_stable_id=True)]
    if body:
        lines.append(body)
    lines.append("</skill>")
    return "\n".join(lines).rstrip()


def _render_meta_lines(*, fragment: ContextFragment, include_stable_id: bool) -> list[str]:
    lines: list[str] = []
    if fragment.metadata:
        for key, value in sorted(fragment.metadata.items()):
            if isinstance(value, str) and value:
                lines.append(_xml_line(key, value))
    if include_stable_id and isinstance(fragment.stable_id, str) and fragment.stable_id:
        lines.append(_xml_line("stable_id", fragment.stable_id))
    if isinstance(fragment.scope, str) and fragment.scope:
        lines.append(_xml_line("scope", fragment.scope))
    if isinstance(fragment.source_path, str) and fragment.source_path:
        lines.append(_xml_line("path", fragment.source_path))
    if isinstance(fragment.source_hash, str) and fragment.source_hash:
        lines.append(_xml_line("sha256", fragment.source_hash))
    return lines


def _xml_line(tag: str, value: str) -> str:
    return f"<{tag}>{html.escape(value, quote=False)}</{tag}>"
