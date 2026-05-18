from __future__ import annotations

import argparse
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import uvicorn
import yaml

from anyagent.agent_packs import AgentPackError, load_agent_catalog
from anyagent.observability import configure_observability_from_env
from anyagent.protocol.credential_vault import (
    AdminCredentialListResponse,
    AdminCredentialRef,
    AdminCredentialSetRequest,
    CredentialScope,
)
from anyagent.protocol.workspace import WorkspaceDoctorFinding, WorkspaceDoctorReport, WorkspaceInitResult
from anyagent.server import create_app
from anyagent.server.migrations import apply_storage_migrations
from anyagent.skills import SkillRoot, default_skill_roots, discover_skills, resolve_disabled_skill_stable_ids


@dataclass(frozen=True, slots=True)
class _AdminClient:
    url: str
    key: str

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.key}"}

    def set_credential(self, req: AdminCredentialSetRequest) -> AdminCredentialRef:
        r = httpx.post(
            f"{self.url}/admin/credentials",
            headers=self._headers(),
            json=req.model_dump(exclude_none=True),
            timeout=15.0,
        )
        _raise_for_status(r)
        return AdminCredentialRef.model_validate(r.json())

    def list_credentials(self) -> AdminCredentialListResponse:
        r = httpx.get(
            f"{self.url}/admin/credentials",
            headers=self._headers(),
            timeout=15.0,
        )
        _raise_for_status(r)
        return AdminCredentialListResponse.model_validate(r.json())

    def delete_credential(self, credential_id: str) -> dict[str, Any]:
        r = httpx.delete(
            f"{self.url}/admin/credentials/{credential_id}",
            headers=self._headers(),
            timeout=15.0,
        )
        _raise_for_status(r)
        obj = r.json()
        if not isinstance(obj, dict):
            raise ValueError("unexpected delete response (not an object)")
        return obj

    def storage_health(self) -> dict[str, Any]:
        r = httpx.get(
            f"{self.url}/admin/storage/health",
            headers=self._headers(),
            timeout=15.0,
        )
        _raise_for_status(r)
        obj = r.json()
        if not isinstance(obj, dict):
            raise ValueError("unexpected storage health response (not an object)")
        return obj


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="anyagent")
    sub = parser.add_subparsers(dest="cmd", required=True)

    init = sub.add_parser("init", help="Create a minimal configurable anyagent workspace.")
    init.add_argument("--workspace", default=".", help="Workspace root to initialize.")
    init.add_argument("--agent-id", default="main", help="Agent id to create (default: main).")
    init.add_argument(
        "--template",
        choices=["basic", "coding-agent", "research-agent", "multi-agent-team"],
        default="basic",
        help="Workspace template to generate (default: basic).",
    )
    init.add_argument("--force", action="store_true", help="Overwrite files created by this command.")
    init.add_argument(
        "--with-example-skill",
        action="store_true",
        help="Create `.agents/skills/example-skill/SKILL.md` and select it by default.",
    )

    doctor = sub.add_parser("doctor", help="Validate an anyagent workspace before serving it.")
    doctor.add_argument("--workspace", default=".", help="Workspace root containing `.agents/`.")
    doctor.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    serve = sub.add_parser("serve", help="Start the built-in anyagent server.")
    serve.add_argument("--workspace", default=".", help="Workspace root containing `.agents/`.")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8787)
    serve.add_argument("--api-key", default=None, help="Bearer token for `/v1/*` and `/internal/*` APIs.")
    serve.add_argument("--admin-key", default=None, help="Bearer token for `/admin/*` APIs.")
    serve.add_argument(
        "--cors-origin",
        action="append",
        default=None,
        help=(
            "Allowed browser origin for CORS. May be repeated. "
            "Defaults to comma-separated $ANYAGENT_CORS_ORIGINS when unset."
        ),
    )
    serve.add_argument("--sandbox-root", default=None, help="Optional root dir for local sandbox sessions.")
    serve.add_argument(
        "--storage-mode",
        choices=["none", "external"],
        default=None,
        help="Unified server storage mode (default: $STORAGE_MODE or none).",
    )
    serve.add_argument(
        "--event-store-backend",
        choices=["inmemory", "external", "redis"],
        default=None,
        help="Event Store backend override (default resolved from storage mode).",
    )
    serve.add_argument(
        "--run-store-backend",
        choices=["inmemory", "external", "redis"],
        default=None,
        help="Run Store backend override (default resolved from storage mode).",
    )
    serve.add_argument(
        "--session-store-backend",
        choices=["inmemory", "external", "redis"],
        default=None,
        help="Session Store backend override (default resolved from storage mode).",
    )
    serve.add_argument(
        "--session-lock-backend",
        choices=["inmemory", "external", "redis"],
        default=None,
        help="Session lease backend (default: $SESSION_LOCK_BACKEND or inmemory).",
    )
    serve.add_argument(
        "--session-lease-ttl-s",
        type=float,
        default=None,
        help="Session lease TTL seconds (default: $SESSION_LEASE_TTL_S or 30).",
    )

    storage_health = sub.add_parser("storage-health", help="Check built-in server storage backends and connectivity.")
    _add_common_admin_flags(storage_health)

    migrate = sub.add_parser("storage-migrate", help="Apply PostgreSQL storage migrations.")
    migrate.add_argument("--postgres-dsn", default=None, help="Override POSTGRES_DSN.")
    migrate.add_argument("--postgres-schema", default=None, help="Override POSTGRES_SCHEMA.")
    migrate.add_argument("--dry-run", action="store_true", help="Only print planned migrations.")

    cred = sub.add_parser("credential", help="Manage credentials via built-in Admin API.")
    cred_sub = cred.add_subparsers(dest="cred_cmd", required=True)

    _add_common_admin_flags(cred)

    p_set = cred_sub.add_parser("set", help="Set (create/update) a credential (write-only).")
    _add_common_admin_flags(p_set)
    p_set.add_argument("--id", dest="credential_id", required=True)
    p_set.add_argument("--kind", required=True)
    p_set.add_argument("--value", default=None, help="Plaintext value (avoid shell history).")
    p_set.add_argument("--value-from-env", default=None, help="Read plaintext value from env var.")
    p_set.add_argument("--scope", choices=["global", "agent"], default="global")
    p_set.add_argument("--agent-id", default=None, help="Required when --scope=agent.")
    p_set.add_argument("--display-name", default=None)
    p_set.add_argument("--provider", default=None)
    p_set.add_argument("--env-var-name", default=None, help="Optional: metadata.env_var_name for EnvBackend.")
    p_set.add_argument("--metadata-json", default=None, help="Extra metadata JSON object.")

    p_list = cred_sub.add_parser("list", help="List credential references (no plaintext).")
    _add_common_admin_flags(p_list)
    p_list.add_argument("--json", action="store_true", help="Print JSON (default).")

    p_delete = cred_sub.add_parser("delete", help="Delete a credential by id.")
    _add_common_admin_flags(p_delete)
    p_delete.add_argument("--id", dest="credential_id", required=True)

    p_import = cred_sub.add_parser("import", help="Import credentials from a YAML file.")
    _add_common_admin_flags(p_import)
    p_import.add_argument("--file", required=True, help="YAML file path (credentials.yaml).")
    p_import.add_argument("--dry-run", action="store_true")
    p_import.add_argument("--skip-missing", action="store_true", help="Skip items with empty resolved value.")

    args = parser.parse_args(argv)
    if args.cmd == "init":
        return _cmd_init(args)
    if args.cmd == "doctor":
        return _cmd_doctor(args)
    if args.cmd == "serve":
        return _cmd_serve(args)
    if args.cmd == "storage-health":
        client = _admin_client_from_args(args)
        print(json.dumps(client.storage_health(), ensure_ascii=False))
        return 0
    if args.cmd == "storage-migrate":
        result = apply_storage_migrations(
            postgres_dsn=args.postgres_dsn,
            postgres_schema=args.postgres_schema,
            dry_run=bool(args.dry_run),
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if args.cmd != "credential":
        parser.error("unsupported command")

    client = _admin_client_from_args(args)

    if args.cred_cmd == "set":
        value = _resolve_value(value=args.value, value_from_env=args.value_from_env)
        scope = _parse_scope(level=args.scope, agent_id=args.agent_id)
        metadata = _build_metadata(
            display_name=args.display_name,
            provider=args.provider,
            env_var_name=args.env_var_name,
            metadata_json=args.metadata_json,
        )
        ref = client.set_credential(
            AdminCredentialSetRequest(
                credential_id=args.credential_id,
                kind=args.kind,
                value=value,
                scope=scope,
                metadata=metadata,
            )
        )
        print(json.dumps(ref.model_dump(exclude_none=True), ensure_ascii=False))
        return 0

    if args.cred_cmd == "list":
        resp = client.list_credentials()
        print(json.dumps(resp.model_dump(exclude_none=True), ensure_ascii=False))
        return 0

    if args.cred_cmd == "delete":
        obj = client.delete_credential(args.credential_id)
        print(json.dumps(obj, ensure_ascii=False))
        return 0

    if args.cred_cmd == "import":
        return _cmd_import(client, file_path=args.file, dry_run=args.dry_run, skip_missing=args.skip_missing)

    parser.error("unsupported credential command")


def _cmd_serve(args: argparse.Namespace) -> int:
    configure_observability_from_env()
    api_key = args.api_key or os.getenv("ANYAGENT_API_KEY")
    admin_key = args.admin_key or os.getenv("ADMIN_API_KEY")
    app = create_app(
        workspace_dir=args.workspace,
        api_key=api_key,
        admin_api_key=admin_key,
        sandbox_root_dir=args.sandbox_root,
        storage_mode=args.storage_mode,
        event_store_backend=args.event_store_backend,
        run_store_backend=args.run_store_backend,
        session_store_backend=args.session_store_backend,
        session_lock_backend=args.session_lock_backend,
        session_lease_ttl_s=args.session_lease_ttl_s,
        cors_origins=args.cors_origin,
    )
    uvicorn.run(app, host=args.host, port=int(args.port), log_level="info")
    return 0


def _cmd_init(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    agent_id = _validate_init_agent_id(str(args.agent_id))
    template = str(args.template or "basic")
    force = bool(args.force)
    created: list[str] = []
    skipped: list[str] = []

    selected_skills = ["example-skill"] if bool(args.with_example_skill) else []
    _write_file(
        workspace / "AGENTS.md",
        _workspace_instructions_for_template(template),
        force=force,
        created=created,
        skipped=skipped,
    )
    for spec in _init_agent_specs(template=template, primary_agent_id=agent_id, selected_skills=selected_skills):
        agent_dir = workspace / ".agents" / "agents" / spec["agent_id"]
        _write_file(
            agent_dir / "agent.yaml",
            _render_agent_yaml(
                selected_skills=list(spec["selected_skills"]),
                requested_tool_names=list(spec["requested_tool_names"]),
                sandbox_mode=str(spec["sandbox_mode"]),
                spawn_allow_agent_ids=list(spec["spawn_allow_agent_ids"]),
            ),
            force=force,
            created=created,
            skipped=skipped,
        )
        _write_file(
            agent_dir / "AGENTS.md",
            str(spec["instructions"]),
            force=force,
            created=created,
            skipped=skipped,
        )
        _write_file(
            agent_dir / "mcp.json",
            _DEFAULT_MCP_JSON,
            force=force,
            created=created,
            skipped=skipped,
        )
    _write_file(
        workspace / ".agents" / "skills" / ".gitkeep",
        "",
        force=force,
        created=created,
        skipped=skipped,
    )
    if bool(args.with_example_skill) or template in {"coding-agent", "research-agent", "multi-agent-team"}:
        _write_file(
            workspace / ".agents" / "skills" / "example-skill" / "SKILL.md",
            _DEFAULT_EXAMPLE_SKILL,
            force=force,
            created=created,
            skipped=skipped,
        )

    payload = {
        "ok": True,
        "workspace": str(workspace),
        "agent_id": agent_id,
        "created": created,
        "skipped": skipped,
        "next": f"anyagent doctor --workspace {workspace}",
    }
    result = WorkspaceInitResult.model_validate(payload)
    print(result.model_dump_json(exclude_none=True))
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    findings = _doctor_workspace(workspace)
    ok = not any(item.level == "error" for item in findings)
    payload = WorkspaceDoctorReport(ok=ok, workspace=str(workspace), findings=findings)
    if bool(args.json):
        print(payload.model_dump_json(exclude_none=True))
    else:
        print(f"anyagent doctor: {'ok' if ok else 'failed'}")
        print(f"workspace: {workspace}")
        for item in payload.findings:
            print(f"[{item.level}] {item.code}: {item.message}")
    return 0 if ok else 1


def _doctor_workspace(workspace: Path) -> list[WorkspaceDoctorFinding]:
    findings: list[WorkspaceDoctorFinding] = []

    def add(level: str, code: str, message: str) -> None:
        findings.append(WorkspaceDoctorFinding.model_validate({"level": level, "code": code, "message": message}))

    root = workspace / ".agents" / "agents"
    if not root.is_dir():
        add("error", "missing_agent_root", f"missing agent packs root: {root}")
        return findings

    try:
        catalog = load_agent_catalog(workspace_dir=workspace)
    except AgentPackError as e:
        add("error", "agent_catalog_invalid", str(e))
        return findings
    except Exception as e:  # noqa: BLE001
        add("error", "agent_catalog_error", str(e))
        return findings

    if not catalog.packs:
        add("error", "no_agents", f"no agent packs found under: {root}")
        return findings

    main = catalog.get("main")
    if main is None:
        add("warning", "missing_main_agent", "no agent_id=main pack found; `anyagent serve` currently requires exposed main")
    elif not main.spec.exposed:
        add("error", "main_not_exposed", "agent_id=main exists but exposed=false; `anyagent serve` requires exposed main")

    for pack in catalog.packs.values():
        add("info", "agent_loaded", f"agent {pack.agent_id}: exposed={pack.spec.exposed} sandbox={pack.spec.sandbox.mode}")
        if not pack.spec.tools.requested_tool_names:
            add("warning", "agent_no_tools", f"agent {pack.agent_id} requests no tools")
        if pack.spec.sandbox.mode == "opensandbox":
            add("error", "opensandbox_unavailable", f"agent {pack.agent_id} uses opensandbox, which this build does not implement")

        skills, skill_errors = discover_skills(
            [SkillRoot(scope="agent", root=pack.skills_dir), *default_skill_roots(workspace_dir=workspace)]
        )
        for path, reason in skill_errors:
            add("warning", "skill_load_error", f"{path}: {reason}")
        disabled_ids = resolve_disabled_skill_stable_ids(
            pack.spec.skills.disabled_paths,
            skills=skills,
            base_dir=pack.root_dir,
        )
        visible_skill_names = {skill.frontmatter.name for skill in skills if skill.stable_id not in disabled_ids}
        for name in pack.spec.skills.default_selected or []:
            if isinstance(name, str) and name.startswith("skill://"):
                continue
            if name not in visible_skill_names:
                add("warning", "skill_not_found", f"agent {pack.agent_id} selects missing skill: {name}")

        if pack.mcp_config is not None:
            for label, server in sorted(pack.mcp_config.mcpServers.items()):
                transport = server.infer_transport().value
                add("info", "mcp_server_loaded", f"agent {pack.agent_id} mcp {label}: transport={transport}")
                if server.command:
                    command = server.command.strip()
                    if os.sep not in command and shutil.which(command) is None:
                        add("warning", "mcp_command_missing", f"agent {pack.agent_id} mcp {label} command not found: {command}")
                    if server.cwd and not Path(server.cwd).expanduser().exists():
                        add("warning", "mcp_cwd_missing", f"agent {pack.agent_id} mcp {label} cwd missing: {server.cwd}")

    if not findings:
        add("info", "workspace_ok", "workspace is valid")
    return findings


def _validate_init_agent_id(agent_id: str) -> str:
    value = agent_id.strip()
    if not value:
        raise SystemExit("--agent-id must be non-empty")
    if len(value) > 64 or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for ch in value):
        raise SystemExit("--agent-id must match [a-zA-Z0-9_.-]{1,64}")
    return value


def _write_file(path: Path, text: str, *, force: bool, created: list[str], skipped: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        skipped.append(str(path))
        return
    path.write_text(text, encoding="utf-8")
    created.append(str(path))


def _render_agent_yaml(
    *,
    selected_skills: list[str],
    requested_tool_names: list[str] | None = None,
    sandbox_mode: str = "disabled",
    spawn_allow_agent_ids: list[str] | None = None,
) -> str:
    skills_block = (
        "  default_selected: []\n"
        if not selected_skills
        else "  default_selected:\n" + "".join(f"    - {name}\n" for name in selected_skills)
    )
    tools = list(requested_tool_names or [])
    tools_block = (
        "  requested_tool_names: []\n"
        if not tools
        else "  requested_tool_names:\n" + "".join(f"    - {name}\n" for name in tools)
    )
    spawn_ids = list(spawn_allow_agent_ids or [])
    spawn_block = (
        "  spawn_allow_agent_ids: []\n"
        if not spawn_ids
        else "  spawn_allow_agent_ids:\n" + "".join(f"    - {agent_id}\n" for agent_id in spawn_ids)
    )
    return (
        "exposed: true\n"
        "tools:\n"
        f"{tools_block}"
        "skills:\n"
        f"{skills_block}"
        "sandbox:\n"
        f"  mode: {sandbox_mode}\n"
        "multiagent:\n"
        f"{spawn_block}"
    )


def _workspace_instructions_for_template(template: str) -> str:
    return f"""# Workspace Instructions

This workspace was generated by `anyagent init --template {template}`.

- Agent behavior lives in `.agents/agents/<agent_id>/AGENTS.md`.
- Tool, skill, sandbox, MCP, and multi-agent boundaries live in `agent.yaml` and `mcp.json`.
- Do not store plaintext credentials in repository files; use the Admin Credential API.
"""


def _init_agent_specs(*, template: str, primary_agent_id: str, selected_skills: list[str]) -> list[dict[str, object]]:
    if template == "coding-agent":
        return [
            {
                "agent_id": primary_agent_id,
                "selected_skills": selected_skills,
                "requested_tool_names": ["exec"],
                "sandbox_mode": "local-unsafe",
                "spawn_allow_agent_ids": [],
                "instructions": _CODING_AGENT_INSTRUCTIONS,
            }
        ]
    if template == "research-agent":
        return [
            {
                "agent_id": primary_agent_id,
                "selected_skills": selected_skills,
                "requested_tool_names": ["core.web_fetch"],
                "sandbox_mode": "disabled",
                "spawn_allow_agent_ids": [],
                "instructions": _RESEARCH_AGENT_INSTRUCTIONS,
            }
        ]
    if template == "multi-agent-team":
        coordinator = primary_agent_id
        child_ids = ["researcher", "coder"] if coordinator not in {"researcher", "coder"} else ["researcher-helper", "coder-helper"]
        return [
            {
                "agent_id": coordinator,
                "selected_skills": selected_skills,
                "requested_tool_names": [],
                "sandbox_mode": "disabled",
                "spawn_allow_agent_ids": child_ids,
                "instructions": _COORDINATOR_AGENT_INSTRUCTIONS.format(researcher=child_ids[0], coder=child_ids[1]),
            },
            {
                "agent_id": child_ids[0],
                "selected_skills": selected_skills,
                "requested_tool_names": ["core.web_fetch"],
                "sandbox_mode": "disabled",
                "spawn_allow_agent_ids": [],
                "instructions": _RESEARCH_AGENT_INSTRUCTIONS,
            },
            {
                "agent_id": child_ids[1],
                "selected_skills": selected_skills,
                "requested_tool_names": ["exec"],
                "sandbox_mode": "local-unsafe",
                "spawn_allow_agent_ids": [],
                "instructions": _CODING_AGENT_INSTRUCTIONS,
            },
        ]
    return [
        {
            "agent_id": primary_agent_id,
            "selected_skills": selected_skills,
            "requested_tool_names": [],
            "sandbox_mode": "disabled",
            "spawn_allow_agent_ids": [],
            "instructions": _BASIC_AGENT_INSTRUCTIONS,
        }
    ]


_BASIC_AGENT_INSTRUCTIONS = """# Main Agent

You are the default anyagent assistant for this workspace.

- Follow the user's request directly.
- Use configured skills when they apply.
- Use configured MCP tools only through their exposed tool names.
- Do not treat AGENTS.md as a permission source; tool access is controlled by agent.yaml and the server.
"""


_CODING_AGENT_INSTRUCTIONS = """# Coding Agent

You are a coding-focused anyagent assistant.

- Inspect the relevant files before proposing code changes.
- Prefer small, reviewable edits that match the existing project style.
- Use `exec` for local verification when available.
- Report changed files and verification results clearly.
- Do not read or print secrets from the environment.
"""


_RESEARCH_AGENT_INSTRUCTIONS = """# Research Agent

You are a research-focused anyagent assistant.

- Break broad questions into concrete search and synthesis steps.
- Prefer primary sources and cite stable facts when possible.
- Keep raw source excerpts short and summarize in your own words.
- Distinguish verified facts from assumptions.
"""


_COORDINATOR_AGENT_INSTRUCTIONS = """# Coordinator Agent

You coordinate work across specialized agents.

- Use `{researcher}` for discovery, source gathering, and factual synthesis.
- Use `{coder}` for implementation-oriented work and verification.
- Keep parent context separate from child agent contexts.
- Summarize decisions and handoff points explicitly.
"""


_DEFAULT_MCP_JSON = """{
  "mcpServers": {}
}
"""


_DEFAULT_EXAMPLE_SKILL = """---
name: example-skill
description: Minimal example skill generated by `anyagent init`.
metadata:
  short-description: Example skill
---

# Example Skill

Use this skill when the user asks for a simple demonstration of workspace-local skills.
"""


def _add_common_admin_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--admin-url",
        default=None,
        help="Admin API base URL (default: $ADMIN_URL or http://127.0.0.1:8787).",
    )
    p.add_argument("--admin-key", default=None, help="Admin API key (default: $ADMIN_API_KEY).")


def _admin_client_from_args(args: argparse.Namespace) -> _AdminClient:
    url = args.admin_url or os.getenv("ADMIN_URL") or "http://127.0.0.1:8787"
    key = args.admin_key or os.getenv("ADMIN_API_KEY") or ""
    if not key.strip():
        raise SystemExit("ADMIN_API_KEY is required (use --admin-key or env var)")
    return _AdminClient(url=url.rstrip("/"), key=key.strip())


def _resolve_value(*, value: str | None, value_from_env: str | None) -> str:
    if value is not None and value_from_env is not None:
        raise SystemExit("provide only one of --value or --value-from-env")
    if value_from_env is not None:
        env_name = value_from_env.strip()
        if not env_name:
            raise SystemExit("--value-from-env must be a non-empty env var name")
        v = os.getenv(env_name)
        if v is None or not v.strip():
            raise SystemExit(f"env var is empty: {env_name}")
        return v.strip()
    if value is None or not str(value).strip():
        raise SystemExit("--value is required (or use --value-from-env)")
    return str(value).strip()


def _parse_scope(*, level: str, agent_id: str | None) -> CredentialScope:
    if level == "global":
        return CredentialScope(level="global")
    if level == "agent":
        if not agent_id or not agent_id.strip():
            raise SystemExit("--agent-id is required when --scope=agent")
        return CredentialScope(level="agent", agent_id=agent_id.strip())
    raise SystemExit(f"unsupported scope: {level}")


def _build_metadata(
    *,
    display_name: str | None,
    provider: str | None,
    env_var_name: str | None,
    metadata_json: str | None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if metadata_json:
        try:
            obj = json.loads(metadata_json)
        except Exception as e:
            raise SystemExit(f"--metadata-json must be valid JSON: {e}") from e
        if not isinstance(obj, dict):
            raise SystemExit("--metadata-json must decode to an object")
        metadata.update(obj)

    if display_name:
        metadata["display_name"] = display_name
    if provider:
        metadata["provider"] = provider
    if env_var_name:
        metadata["env_var_name"] = env_var_name
    return metadata


def _cmd_import(client: _AdminClient, *, file_path: str, dry_run: bool, skip_missing: bool) -> int:
    p = file_path.strip()
    if not p:
        raise SystemExit("--file must be non-empty")
    with open(p, "r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)

    if not isinstance(doc, dict):
        raise SystemExit("credentials file must be a YAML object")
    items = doc.get("credentials")
    if not isinstance(items, list):
        raise SystemExit("credentials file must include 'credentials: [...]'")

    ok = 0
    skipped = 0
    for i, raw in enumerate(items):
        if not isinstance(raw, dict):
            raise SystemExit(f"credentials[{i}] must be an object")

        credential_id = raw.get("credential_id")
        kind = raw.get("kind")
        scope_raw = raw.get("scope")
        metadata = raw.get("metadata") or {}

        if not isinstance(credential_id, str) or not credential_id.strip():
            raise SystemExit(f"credentials[{i}].credential_id must be non-empty string")
        if not isinstance(kind, str) or not kind.strip():
            raise SystemExit(f"credentials[{i}].kind must be non-empty string")
        if not isinstance(scope_raw, dict):
            raise SystemExit(f"credentials[{i}].scope must be an object")
        if not isinstance(metadata, dict):
            raise SystemExit(f"credentials[{i}].metadata must be an object (or omitted)")

        scope = CredentialScope.model_validate(scope_raw)

        value = _import_resolve_value(raw, index=i)
        if not value:
            if skip_missing:
                skipped += 1
                continue
            raise SystemExit(f"credentials[{i}] has empty value (use --skip-missing to ignore)")

        req = AdminCredentialSetRequest(
            credential_id=credential_id.strip(),
            kind=kind.strip(),
            value=value,
            scope=scope,
            metadata=dict(metadata),
        )
        if not dry_run:
            client.set_credential(req)
        ok += 1

    print(json.dumps({"ok": True, "set": ok, "skipped": skipped, "dry_run": dry_run}, ensure_ascii=False))
    return 0


def _import_resolve_value(raw: dict[str, Any], *, index: int) -> str:
    direct = raw.get("value")
    if direct is not None:
        return str(direct).strip()

    env_name = raw.get("value_from_env")
    default_value = raw.get("default_value")
    default_str = "" if default_value is None else str(default_value).strip()

    if env_name is None:
        return default_str
    if not isinstance(env_name, str) or not env_name.strip():
        raise SystemExit(f"credentials[{index}].value_from_env must be string")
    v = os.getenv(env_name.strip(), default_str).strip()
    return v


def _raise_for_status(r: httpx.Response) -> None:
    if 200 <= r.status_code < 300:
        return
    text = r.text
    if len(text) > 2000:
        text = text[:2000] + "...(truncated)"
    raise SystemExit(f"HTTP {r.status_code}: {text}")


if __name__ == "__main__":
    raise SystemExit(main())
