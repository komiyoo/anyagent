from __future__ import annotations

from pathlib import Path

from anyagent.agent_packs import AgentPack, AgentSkillsSpec, AgentSpec, AgentToolsSpec, MultiAgentSpec
from anyagent.agent_runtime import build_default_environment_context_values, build_prompt_envelope
from anyagent.agent_runtime.prompt_injection import build_agents_md_injection_text
from anyagent.agent_runtime.tool_loop_payloads import build_tool_loop_followup_body
from anyagent.agent_runtime.skills_injection import build_skills_injection_text
from anyagent.protocol.context_fragments import ContextFragment, is_context_fragment_text
from anyagent.protocol.sandbox import SandboxPolicy
from anyagent.mcp.models import MCPConfig, MCPServerConfig
from anyagent.skills.models import SkillFrontMatter, SkillPackage


def _build_pack(tmp_path: Path) -> AgentPack:
    root_dir = tmp_path / "main"
    root_dir.mkdir()
    agents_md_path = root_dir / "AGENTS.md"
    agents_md_text = "你是一个测试 agent。\n遵循结构化上下文。"
    agents_md_path.write_text(agents_md_text, encoding="utf-8")
    return AgentPack(
        agent_id="main",
        root_dir=root_dir,
        spec=AgentSpec(
            exposed=True,
            tools=AgentToolsSpec(requested_tool_names=["core.web_fetch"]),
            skills=AgentSkillsSpec(default_selected=[]),
            sandbox=SandboxPolicy(),
            multiagent=MultiAgentSpec(),
        ),
        agents_md_path=agents_md_path,
        agents_md_text=agents_md_text,
        agents_md_sha256="abc123",
        workspace_agents_md_path=None,
        workspace_agents_md_text=None,
        workspace_agents_md_sha256=None,
        mcp_config=None,
    )


def _build_skill(tmp_path: Path) -> SkillPackage:
    skill_dir = tmp_path / "skill-a"
    skill_dir.mkdir()
    skill_md_path = skill_dir / "SKILL.md"
    skill_md_path.write_text(
        "---\nname: repo-helper\ndescription: help with repo tasks\n---\nRead the repo carefully.\n",
        encoding="utf-8",
    )
    return SkillPackage(
        skill_dir=skill_dir,
        skill_md_path=skill_md_path,
        scope="repo",
        frontmatter=SkillFrontMatter(name="repo-helper", description="help with repo tasks"),
        body_markdown="Read the repo carefully.\n",
        agent_metadata={"interface": {"default_prompt": "Inspect the repo first."}},
    )


def test_build_agents_md_injection_text_uses_structured_fragment(tmp_path: Path) -> None:
    text = build_agents_md_injection_text(_build_pack(tmp_path))
    assert text.startswith("# AGENTS.md instructions for agent:main")
    assert "<INSTRUCTIONS>" in text
    assert "<INSTRUCTIONS_META>" not in text
    assert "<path>" not in text
    assert "<sha256>" not in text


def test_build_skills_injection_text_uses_skill_catalog_metadata_with_path(tmp_path: Path) -> None:
    text = build_skills_injection_text([_build_skill(tmp_path)])
    assert text.startswith("<skill_catalog>")
    assert "<name>repo-helper</name>" in text
    assert "<description>help with repo tasks</description>" in text
    assert "<path>" in text
    assert "<sha256>" in text
    assert "Read the repo carefully." not in text


def test_prompt_envelope_applies_fragments_and_prompt_cache_key(tmp_path: Path) -> None:
    pack = _build_pack(tmp_path)
    skill = _build_skill(tmp_path)
    envelope = build_prompt_envelope(pack=pack, selected_skills=[skill], model="gpt-5")
    body = {"input": [{"role": "user", "content": "hello"}]}
    out = envelope.apply_to_body(body=body)
    assert isinstance(out.get("prompt_cache_key"), str) and out["prompt_cache_key"]
    assert out["input"][0]["role"] == "developer"
    assert out["input"][0]["content"].startswith("# AGENTS.md instructions for agent:main")
    assert out["input"][1]["role"] == "developer"
    assert out["input"][1]["content"].startswith("<skill_catalog>")
    assert "Read the repo carefully." not in out["input"][1]["content"]
    assert out["input"][2] == {"role": "user", "content": "hello"}


def test_prompt_envelope_catalog_lists_available_skills_and_marks_selected(tmp_path: Path) -> None:
    pack = _build_pack(tmp_path)
    selected = _build_skill(tmp_path)
    other_dir = tmp_path / "skill-b"
    other_dir.mkdir()
    other_md = other_dir / "SKILL.md"
    other_md.write_text("---\nname: itinerary\ndescription: trip planning\n---\nPlan trips.\n", encoding="utf-8")
    other = SkillPackage(
        skill_dir=other_dir,
        skill_md_path=other_md,
        scope="repo",
        frontmatter=SkillFrontMatter(name="itinerary", description="trip planning"),
        body_markdown="Plan trips.\n",
    )

    envelope = build_prompt_envelope(
        pack=pack,
        selected_skills=[selected],
        available_skills=[selected, other],
        model="gpt-5",
    )
    rendered = "\n".join(fragment.rendered_text for fragment in envelope.rendered_fragments())

    assert "<name>repo-helper</name>" in rendered
    assert "<name>itinerary</name>" in rendered
    assert rendered.count("<selected>true</selected>") == 1
    assert "Read the repo carefully." not in rendered
    assert "Plan trips." not in rendered


def test_prompt_envelope_appends_business_context_as_independent_fragment(tmp_path: Path) -> None:
    pack = _build_pack(tmp_path)
    skill = _build_skill(tmp_path)

    envelope = build_prompt_envelope(
        pack=pack,
        selected_skills=[],
        available_skills=[skill],
        model="gpt-5",
        context_fragments=[
            ContextFragment(
                kind="business_context",
                cache_class="contextual",
                stable_id="route://golden-triangle",
                body="# ROUTE_CONTEXT\n\n<route_context>\nGolden Triangle facts\n</route_context>",
            )
        ],
    )
    out = envelope.apply_to_body(body={"input": [{"role": "user", "content": "hello"}]})

    assert out["input"][0]["content"].startswith("# AGENTS.md instructions for agent:main")
    assert out["input"][1]["content"].startswith("<skill_catalog>")
    assert out["input"][2]["content"].startswith("# ROUTE_CONTEXT")
    assert "<INSTRUCTIONS>" not in out["input"][2]["content"]


def test_prompt_envelope_audit_metadata_includes_compacted_summary_fields(tmp_path: Path) -> None:
    pack = _build_pack(tmp_path)
    skill = _build_skill(tmp_path)
    envelope = build_prompt_envelope(pack=pack, selected_skills=[skill], model="gpt-5")

    audit = envelope.audit_metadata()

    assert audit.prompt_cache_key == envelope.prompt_cache_key
    assert audit.fragment_count == 2
    assert audit.retained_fragment_count == 2
    assert audit.stable_prefix_count == 2
    assert audit.contextual_count == 0
    assert audit.dynamic_count == 0
    assert audit.fragment_kinds == ["agents_instructions", "skill_catalog"]
    assert audit.compacted is False


def test_prompt_envelope_ignores_workspace_agents_and_supports_system_fallback_role(tmp_path: Path) -> None:
    pack = _build_pack(tmp_path)
    workspace_agents = tmp_path / "AGENTS.md"
    workspace_agents.write_text("这是 workspace 级指令。\n", encoding="utf-8")
    pack = AgentPack(
        agent_id=pack.agent_id,
        root_dir=pack.root_dir,
        spec=pack.spec,
        agents_md_path=pack.agents_md_path,
        agents_md_text=pack.agents_md_text,
        agents_md_sha256=pack.agents_md_sha256,
        workspace_agents_md_path=workspace_agents,
        workspace_agents_md_text="这是 workspace 级指令。\n",
        workspace_agents_md_sha256="workspace123",
        mcp_config=pack.mcp_config,
    )

    envelope = build_prompt_envelope(pack=pack, selected_skills=[], model="gpt-5", instruction_role="system")
    out = envelope.apply_to_body(body={"input": [{"role": "user", "content": "hello"}]})

    assert out["input"][0]["role"] == "system"
    assert out["input"][0]["content"].startswith("# AGENTS.md instructions for agent:main")
    assert "workspace" not in out["input"][0]["content"]
    assert out["input"][1] == {"role": "user", "content": "hello"}
    assert envelope.audit_metadata().fragment_kinds == ["agents_instructions"]


def test_prompt_envelope_cache_key_is_stable_for_same_inputs(tmp_path: Path) -> None:
    pack = _build_pack(tmp_path)
    skill = _build_skill(tmp_path)
    left = build_prompt_envelope(pack=pack, selected_skills=[skill], model="gpt-5")
    right = build_prompt_envelope(pack=pack, selected_skills=[skill], model="gpt-5")
    assert left.prompt_cache_key == right.prompt_cache_key


def test_prompt_envelope_includes_environment_context_without_changing_stable_key(tmp_path: Path) -> None:
    pack = _build_pack(tmp_path)
    env_a = build_default_environment_context_values(cwd=tmp_path, sandbox_mode=pack.spec.sandbox.mode)
    env_b = dict(env_a)
    env_b["current_date"] = "2099-01-01"
    left = build_prompt_envelope(pack=pack, selected_skills=[], model="gpt-5", environment_values=env_a)
    right = build_prompt_envelope(pack=pack, selected_skills=[], model="gpt-5", environment_values=env_b)
    body = left.apply_to_body(body={"input": [{"role": "user", "content": "hello"}]})
    assert left.prompt_cache_key == right.prompt_cache_key
    assert not any(
        isinstance(item.get("content"), str) and item["content"].startswith("<environment_context>")
        for item in body["input"]
        if isinstance(item, dict)
    )


def test_prompt_envelope_includes_sandbox_guidance_and_mcp_refs_when_available(tmp_path: Path) -> None:
    pack = _build_pack(tmp_path)
    pack = AgentPack(
        agent_id=pack.agent_id,
        root_dir=pack.root_dir,
        spec=AgentSpec(
            exposed=True,
            tools=AgentToolsSpec(requested_tool_names=["exec"]),
            skills=pack.spec.skills,
            sandbox=SandboxPolicy(mode="local-unsafe"),
            multiagent=pack.spec.multiagent,
        ),
        agents_md_path=pack.agents_md_path,
        agents_md_text=pack.agents_md_text,
        agents_md_sha256=pack.agents_md_sha256,
        workspace_agents_md_path=pack.workspace_agents_md_path,
        workspace_agents_md_text=pack.workspace_agents_md_text,
        workspace_agents_md_sha256=pack.workspace_agents_md_sha256,
        mcp_config=MCPConfig(
            mcpServers={
                "github": MCPServerConfig(url="https://mcp.example.test"),
            }
        ),
    )

    envelope = build_prompt_envelope(pack=pack, selected_skills=[], model="gpt-5")
    rendered = envelope.rendered_fragments()

    assert any(fragment.kind == "mcp_server_ref" for fragment in envelope.fragments)
    assert any("<mcp_server_ref>" in fragment.rendered_text for fragment in rendered)
    assert any(fragment.kind == "mcp_server_ref" for fragment in rendered)
    assert not any(fragment.kind == "sandbox_guidance" for fragment in envelope.fragments)
    assert not any("<sandbox_guidance>" in fragment.rendered_text for fragment in rendered)


def test_prompt_envelope_skips_disabled_mcp_refs(tmp_path: Path) -> None:
    pack = _build_pack(tmp_path)
    pack = AgentPack(
        agent_id=pack.agent_id,
        root_dir=pack.root_dir,
        spec=pack.spec,
        agents_md_path=pack.agents_md_path,
        agents_md_text=pack.agents_md_text,
        agents_md_sha256=pack.agents_md_sha256,
        workspace_agents_md_path=pack.workspace_agents_md_path,
        workspace_agents_md_text=pack.workspace_agents_md_text,
        workspace_agents_md_sha256=pack.workspace_agents_md_sha256,
        mcp_config=MCPConfig(
            mcpServers={
                "enabled": MCPServerConfig(url="https://enabled.example.test"),
                "disabled": MCPServerConfig(enabled=False, url="https://disabled.example.test"),
            }
        ),
    )

    envelope = build_prompt_envelope(pack=pack, selected_skills=[], model="gpt-5")
    rendered = "\n".join(fragment.rendered_text for fragment in envelope.rendered_fragments())

    assert "<label>enabled</label>" in rendered
    assert "<label>disabled</label>" not in rendered


def test_context_fragment_detection_recognizes_agents_skill_and_environment_texts(tmp_path: Path) -> None:
    agents_text = build_agents_md_injection_text(_build_pack(tmp_path))
    skill_text = build_skills_injection_text([_build_skill(tmp_path)])
    env_text = "<environment_context>\n<shell>zsh</shell>\n</environment_context>"
    assert is_context_fragment_text(agents_text)
    assert is_context_fragment_text(skill_text)
    assert is_context_fragment_text(env_text)


def test_tool_loop_followup_body_preserves_prompt_cache_key() -> None:
    body = build_tool_loop_followup_body(
        previous_response_id="resp_prev",
        tool_outputs=[{"type": "function_call_output", "call_id": "call_1", "output": "ok"}],
        manifest_tools=[],
        metadata={"agent_id": "main"},
        tool_choice="auto",
        stream=False,
        model="gpt-5",
        prompt_cache_key="cache-123",
    )
    assert body["prompt_cache_key"] == "cache-123"
