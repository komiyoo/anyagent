from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from anyagent.agent_packs import load_agent_catalog
from anyagent.server.app import create_app
from anyagent.server.internal_skills import create_internal_skills_router
from anyagent.skills import load_skills_from_root


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


def test_internal_skills_router_lists_catalog_fields(tmp_path: Path) -> None:
    skill_md = _write_workspace_with_skill(tmp_path)

    app = FastAPI()
    app.state.workspace_dir = tmp_path
    app.state.agent_catalog = load_agent_catalog(workspace_dir=tmp_path)
    app.state.agent_skills = {}
    app.state.global_skills, app.state.global_skill_errors = load_skills_from_root(
        tmp_path / ".agents" / "skills",
        scope="repo",
    )
    app.state.agent_skill_errors = {}
    app.include_router(create_internal_skills_router(api_key="test-key"))

    with TestClient(app) as client:
        missing_auth = client.get("/internal/skills/list", params={"agent_id": "main"})
        assert missing_auth.status_code == 401

        unknown_agent = client.get(
            "/internal/skills/list",
            params={"agent_id": "missing"},
            headers={"authorization": "Bearer test-key"},
        )
        assert unknown_agent.status_code == 404
        assert unknown_agent.json()["error"]["message"] == "unknown agent_id: missing"

        resp = client.get(
            "/internal/skills/list",
            params={"agent_id": "main"},
            headers={"authorization": "Bearer test-key"},
        )
        assert resp.status_code == 200, resp.text

    payload = resp.json()
    assert payload["agent_id"] == "main"
    assert payload["load_errors"] == []
    assert len(payload["skills"]) == 1

    skill = payload["skills"][0]
    assert skill["name"] == "demo-skill"
    assert skill["path"] == str(skill_md.resolve())
    assert skill["source_hash"] == hashlib.sha256(skill_md.read_bytes()).hexdigest()
    assert skill["interface"] == {
        "display_name": "Demo Skill",
        "default_prompt": "Try the demo skill",
    }
    assert skill["requested_tool_names"] == ["core.web_fetch"]
