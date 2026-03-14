from __future__ import annotations

"""Unit tests for SDK-local prompt explain/example helpers."""

from anyagent import AnyAgent


def test_example_scenarios_expose_catalog_defaults() -> None:
    """内置场景目录应对外暴露稳定的 label 与默认选项。"""

    client = AnyAgent(api_key="test-key", base_url="http://127.0.0.1:8787")

    scenarios = client.prompts.example_scenarios()
    catalog = {item.scenario: item for item in scenarios}

    assert set(catalog) == {"sandbox_file_write", "multi_skill_research", "toolset_retry"}
    assert catalog["sandbox_file_write"].label == "Sandbox File Write"
    assert catalog["multi_skill_research"].default_options.skill_count == 2
    assert catalog["multi_skill_research"].default_options.include_mcp is True
    assert catalog["toolset_retry"].default_options.sandbox_mode == "local-unsafe"


def test_example_run_bundle_applies_local_option_overrides() -> None:
    """本地示例应按 options 覆写 prompt bundle、tool loop 与解释文本。"""

    client = AnyAgent(api_key="test-key", base_url="http://127.0.0.1:8787")

    bundle = client.prompts.example_run_bundle(
        scenario="multi_skill_research",
        options={
            "include_mcp": False,
            "skill_count": 1,
            "sandbox_mode": "disabled",
            "user_input": "请只抓取一个网页并总结",
        },
    )

    assert bundle.options.include_mcp is False
    assert bundle.options.skill_count == 1
    assert bundle.options.sandbox_mode == "disabled"
    assert bundle.prompt_bundle.effective_body["input"] == "请只抓取一个网页并总结"
    assert bundle.prompt_bundle.mcp_servers == []
    assert len(bundle.prompt_bundle.selected_skill_ids) == 1
    assert "exec" not in bundle.prompt_bundle.manifest_tool_names
    assert "core.web_fetch" in bundle.prompt_bundle.manifest_tool_names
    assert not any(item.kind == "sandbox_guidance" for item in bundle.prompt_bundle.rendered_fragments)
    assert bundle.tool_loop_items[0].item["name"] == "core.web_fetch"
    assert "纯本地示例" in bundle.explanation.key_takeaways[0]

