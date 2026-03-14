from __future__ import annotations

from anyagent.protocol.stage_events import PromptFragmentSummary, build_prompt_context_audit


def test_build_prompt_context_audit_counts_and_compacts_duplicate_fragments() -> None:
    audit = build_prompt_context_audit(
        prompt_cache_key="cache_1",
        fragments=[
            PromptFragmentSummary(kind="agents_instructions", cache_class="stable_prefix", stable_id="agents://main"),
            PromptFragmentSummary(kind="skill", cache_class="contextual", stable_id="skill://repo-helper"),
            PromptFragmentSummary(kind="skill", cache_class="contextual", stable_id="skill://repo-helper"),
            PromptFragmentSummary(kind="environment_context", cache_class="contextual", stable_id="environment://runtime"),
        ],
        max_fragments=3,
    )

    assert audit.prompt_cache_key == "cache_1"
    assert audit.fragment_count == 4
    assert audit.retained_fragment_count == 3
    assert audit.stable_prefix_count == 1
    assert audit.contextual_count == 3
    assert audit.dynamic_count == 0
    assert audit.fragment_kinds == ["agents_instructions", "skill", "environment_context"]
    assert audit.compacted is True
    assert [fragment.kind for fragment in audit.fragments] == [
        "agents_instructions",
        "skill",
        "environment_context",
    ]
