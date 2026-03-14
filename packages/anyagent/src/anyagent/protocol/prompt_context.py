from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from anyagent.protocol.context_fragments import ContextFragment


class PromptFragmentSummary(BaseModel):
    """Stable summary of one prompt fragment for audit/replay."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    cache_class: str
    stable_id: str | None = None
    source_path: str | None = None
    source_hash: str | None = None
    scope: str | None = None


class PromptContextAudit(BaseModel):
    """Compacted prompt-context audit summary shared by events and session snapshot."""

    model_config = ConfigDict(extra="forbid")

    prompt_cache_key: str | None = None
    fragments: list[PromptFragmentSummary] = Field(default_factory=list)
    fragment_count: int = Field(default=0, ge=0)
    retained_fragment_count: int = Field(default=0, ge=0)
    stable_prefix_count: int = Field(default=0, ge=0)
    contextual_count: int = Field(default=0, ge=0)
    dynamic_count: int = Field(default=0, ge=0)
    fragment_kinds: list[str] = Field(default_factory=list)
    compacted: bool = False


class PromptEnvelope(BaseModel):
    """Protocol-first prompt envelope model for stable prefix and contextual fragments."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    prompt_cache_key: str | None = None
    fragments: tuple[ContextFragment, ...] = Field(default_factory=tuple)

    def apply_to_body(self, *, body: dict[str, Any]) -> dict[str, Any]:
        from anyagent.agent_runtime.prompt_envelope import apply_prompt_envelope_to_body

        return apply_prompt_envelope_to_body(body=body, envelope=self)

    def audit_metadata(self) -> PromptContextAudit:
        from anyagent.agent_runtime.prompt_envelope import build_prompt_audit_metadata

        return build_prompt_audit_metadata(envelope=self)


def compact_prompt_fragments(
    fragments: list[PromptFragmentSummary | dict[str, Any]],
    *,
    max_fragments: int = 16,
) -> list[PromptFragmentSummary]:
    """Deduplicate prompt fragment summaries while preserving stable order."""

    out: list[PromptFragmentSummary] = []
    seen: set[tuple[str, str, str | None, str | None, str | None, str | None]] = set()
    cap = max(1, int(max_fragments))
    for raw in fragments:
        fragment = _coerce_prompt_fragment_summary(raw)
        if fragment is None:
            continue
        key = (
            fragment.kind,
            fragment.cache_class,
            fragment.stable_id,
            fragment.source_path,
            fragment.source_hash,
            fragment.scope,
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(fragment)
        if len(out) >= cap:
            break
    return out


def build_prompt_context_audit(
    *,
    prompt_cache_key: str | None,
    fragments: list[PromptFragmentSummary | dict[str, Any]],
    max_fragments: int = 16,
) -> PromptContextAudit:
    """Build one compact prompt-context summary for audit, replay, and session snapshot."""

    valid_fragments: list[PromptFragmentSummary] = []
    stable_prefix_count = 0
    contextual_count = 0
    dynamic_count = 0
    fragment_kinds: list[str] = []
    seen_kinds: set[str] = set()

    for raw in fragments:
        fragment = _coerce_prompt_fragment_summary(raw)
        if fragment is None:
            continue
        valid_fragments.append(fragment)
        if fragment.cache_class == "stable_prefix":
            stable_prefix_count += 1
        elif fragment.cache_class == "contextual":
            contextual_count += 1
        else:
            dynamic_count += 1
        if fragment.kind not in seen_kinds:
            seen_kinds.add(fragment.kind)
            fragment_kinds.append(fragment.kind)

    retained = compact_prompt_fragments(valid_fragments, max_fragments=max_fragments)
    return PromptContextAudit(
        prompt_cache_key=prompt_cache_key.strip() if isinstance(prompt_cache_key, str) and prompt_cache_key.strip() else None,
        fragments=retained,
        fragment_count=len(valid_fragments),
        retained_fragment_count=len(retained),
        stable_prefix_count=stable_prefix_count,
        contextual_count=contextual_count,
        dynamic_count=dynamic_count,
        fragment_kinds=fragment_kinds,
        compacted=len(retained) < len(valid_fragments),
    )


def _coerce_prompt_fragment_summary(raw: PromptFragmentSummary | dict[str, Any]) -> PromptFragmentSummary | None:
    try:
        if isinstance(raw, PromptFragmentSummary):
            return raw
        if not isinstance(raw, dict):
            return None
        payload = dict(raw)
        cache_class = payload.get("cache_class")
        if not isinstance(cache_class, str) or not cache_class.strip():
            payload["cache_class"] = "contextual"
        return PromptFragmentSummary.model_validate(payload)
    except Exception:  # noqa: BLE001
        return None
