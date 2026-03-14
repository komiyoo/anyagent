from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from anyagent.server.app import create_app


def _write_workspace_with_skill(root: Path) -> Path:
    agent_dir = root / ".agents" / "agents" / "main"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "AGENTS.md").write_text("你是一个测试 agent。\n", encoding="utf-8")
    (agent_dir / "agent.yaml").write_text(
        """
exposed: true
tools:
  requested_tool_names: []
skills:
  default_selected: []
sandbox:
  mode: local-unsafe
multiagent:
  spawn_allow_agent_ids: []
""".strip()
        + "\n",
        encoding="utf-8",
    )
    skill_dir = root / ".agents" / "skills" / "demo-skill"
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        """---
name: demo-skill
description: Demo skill description
metadata:
  short-description: Demo short description
---
Use this skill for demo tasks.
""",
        encoding="utf-8",
    )
    (skill_dir / "agents").mkdir(parents=True, exist_ok=True)
    (skill_dir / "agents" / "openai.yaml").write_text(
        """
interface:
  display_name: Demo Skill
  default_prompt: Try the demo skill
dependencies:
  tools:
    - transport: core
      value: core.web_fetch
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return skill_md


def test_runtime_skills_list_includes_catalog_fields(tmp_path: Path) -> None:
    asyncio.run(_run_runtime_skills_list_includes_catalog_fields(tmp_path))


async def _run_runtime_skills_list_includes_catalog_fields(tmp_path: Path) -> None:
    skill_md = _write_workspace_with_skill(tmp_path)
    app = create_app(workspace_dir=tmp_path, api_key="user-key", admin_api_key="admin-key")
    runtime = app.state.anyagent.runtime

    response = await runtime.list_skills(agent_id="main")

    skill = next((item for item in response.skills if item.path == str(skill_md.resolve())), None)
    assert skill is not None
    assert skill.name == "demo-skill"
    assert skill.path == str(skill_md.resolve())
    assert skill.source_hash == hashlib.sha256(skill_md.read_bytes()).hexdigest()
    assert skill.interface == {
        "display_name": "Demo Skill",
        "default_prompt": "Try the demo skill",
    }
    assert skill.requested_tool_names == ["core.web_fetch"]
