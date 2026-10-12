from __future__ import annotations

import hashlib
from pathlib import Path

import httpx

from anyagent.protocol.agent_api_internal import InternalSkillsListResponse
from anyagent.server.app import create_app


def _write_workspace_with_skill(root: Path) -> Path:
    agent_dir = root / ".anyagent" / "agents" / "main"
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
    skill_dir = root / ".anyagent" / "skills" / "demo-skill"
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


def test_internal_skills_list_returns_catalog_fields(tmp_path: Path) -> None:
    skill_md = _write_workspace_with_skill(tmp_path)
    app = create_app(
              workspace_dir=tmp_path,
              cli_overrides={
                  "server": {
                      "api_key": "user-key",
                      "admin_api_key": "admin-key",
                  },
              },
          )

    transport = httpx.ASGITransport(app=app)

    async def _run() -> None:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.get(
                "/internal/skills/list",
                params={"agent_id": "main"},
                headers={"Authorization": "Bearer user-key"},
        )
        assert resp.status_code == 200
        payload = InternalSkillsListResponse.model_validate(resp.json())
        skill = next((item for item in payload.skills if item.path == str(skill_md.resolve())), None)
        assert skill is not None
        assert skill.path == str(skill_md.resolve())
        assert skill.source_hash == hashlib.sha256(skill_md.read_bytes()).hexdigest()
        assert skill.interface == {
            "display_name": "Demo Skill",
            "default_prompt": "Try the demo skill",
        }
        assert skill.requested_tool_names == ["core.web_fetch"]

    import asyncio

    asyncio.run(_run())
