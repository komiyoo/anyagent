"""Create a minimal anyagent workspace from a named template."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from anyagent.config.models import get_provider_spec
from anyagent.protocol.workspace import WorkspaceInitResult
from anyagent.scaffold.files import (
    AGENT_SCHEMA_LINE,
    ANYAGENT_SCHEMA_LINE,
    ChangeLog,
    agent_document,
    canonical_provider,
    dump_yaml_with_header,
    effective_sandbox,
    merge_tools,
    next_steps,
    render_env_example,
    render_template,
    validate_agent_id,
    validate_template_name,
)
from anyagent.scaffold.models import InitOptions, ScaffoldError
from anyagent.scaffold.schema_export import write_schema_files

# Built-in defaults already select this pair through the `fast` alias.
_BUILTIN_PROVIDER = "openai"
_BUILTIN_MODEL = "gpt-4o-mini"


@dataclass(frozen=True)
class _AgentPlan:
    agent_id: str
    instructions: str
    tools: list[str]
    sandbox_mode: str
    spawn: list[str]
    skills: list[str]
    primary: bool


def init_workspace(opts: InitOptions) -> WorkspaceInitResult:
    """Write a minimal workspace and return the init result.

    The workspace file records only provider, model, and base URL values that
    differ from built-in defaults. Agent packs omit fields that match
    ``AgentSpec`` defaults. Empty ``mcp.json``, ``.gitkeep``, and ``plugins/demo``
    are not created.
    """

    workspace = Path(opts.workspace).expanduser().resolve()
    if workspace.exists() and not workspace.is_dir():
        raise ScaffoldError(f"workspace is not a directory: {workspace}")
    agent_id = validate_agent_id(opts.agent_id)
    template = validate_template_name(opts.template)
    provider_key, provider_kind, provider_registered = canonical_provider(opts.provider)
    model_name = opts.model.strip() if isinstance(opts.model, str) and opts.model.strip() else None
    base_url = _base_url_override(provider_kind, opts.base_url)
    plans = _agent_plans(
        template=template,
        agent_id=agent_id,
        skills=["example-skill"] if opts.with_example_skill else [],
    )
    plans = [_apply_primary_options(plan, opts) for plan in plans]

    log = ChangeLog(overwrite_as="created")
    workspace.mkdir(parents=True, exist_ok=True)
    write_schema_files(workspace, log, force=opts.force)
    log.write(
        workspace / ".anyagent" / "anyagent.yaml",
        _render_anyagent_yaml(
            provider_key=provider_key,
            provider_registered=provider_registered,
            model_name=model_name,
            base_url=base_url,
        ),
        force=opts.force,
    )
    log.write(
        workspace / "AGENTS.md",
        render_template("workspace/AGENTS.md.tmpl", template=template),
        force=opts.force,
    )
    log.write(workspace / ".gitignore", render_template("workspace/gitignore"), force=opts.force)
    log.write(
        workspace / ".env.example",
        render_env_example(provider=opts.provider),
        force=opts.force,
    )
    for plan in plans:
        agent_dir = workspace / ".anyagent" / "agents" / plan.agent_id
        log.write(agent_dir / "AGENTS.md", plan.instructions, force=opts.force)
        log.write(
            agent_dir / "agent.yaml",
            dump_yaml_with_header(
                [],
                agent_document(
                    tools=plan.tools,
                    skills=plan.skills,
                    sandbox_mode=plan.sandbox_mode,
                    spawn=plan.spawn,
                ),
                AGENT_SCHEMA_LINE,
            ),
            force=opts.force,
        )
    if opts.with_example_skill:
        log.write(
            workspace / ".anyagent" / "skills" / "example-skill" / "SKILL.md",
            render_template("skills/example-skill.md.tmpl"),
            force=opts.force,
        )
    return WorkspaceInitResult(
        ok=True,
        workspace=str(workspace),
        agent_id=agent_id,
        created=log.created,
        skipped=log.skipped,
        next=next_steps(workspace)[0],
    )


def _apply_primary_options(plan: _AgentPlan, opts: InitOptions) -> _AgentPlan:
    if not plan.primary:
        return plan
    return replace(
        plan,
        tools=merge_tools(plan.tools, list(opts.tools), with_web_fetch=opts.with_web_fetch, with_exec=opts.with_exec),
        sandbox_mode=effective_sandbox(plan.sandbox_mode, override=opts.sandbox_mode, with_exec=opts.with_exec),
    )


def _agent_plans(*, template: str, agent_id: str, skills: list[str]) -> list[_AgentPlan]:
    if template == "coding-agent":
        plans = [
            _AgentPlan(
                agent_id=agent_id,
                instructions=render_template("agents/coding.md.tmpl"),
                tools=["exec"],
                sandbox_mode="local-unsafe",
                spawn=[],
                skills=list(skills),
                primary=True,
            )
        ]
    elif template == "research-agent":
        plans = [
            _AgentPlan(
                agent_id=agent_id,
                instructions=render_template("agents/research.md.tmpl"),
                tools=["core.web_fetch"],
                sandbox_mode="disabled",
                spawn=[],
                skills=list(skills),
                primary=True,
            )
        ]
    elif template == "multi-agent-team":
        child_ids = (
            ["researcher", "coder"] if agent_id not in {"researcher", "coder"} else ["researcher-helper", "coder-helper"]
        )
        plans = [
            _AgentPlan(
                agent_id=agent_id,
                instructions=render_template(
                    "agents/coordinator.md.tmpl",
                    researcher=child_ids[0],
                    coder=child_ids[1],
                ),
                tools=[],
                sandbox_mode="disabled",
                spawn=child_ids,
                skills=list(skills),
                primary=True,
            ),
            _AgentPlan(
                agent_id=child_ids[0],
                instructions=render_template("agents/research.md.tmpl"),
                tools=["core.web_fetch"],
                sandbox_mode="disabled",
                spawn=[],
                skills=list(skills),
                primary=False,
            ),
            _AgentPlan(
                agent_id=child_ids[1],
                instructions=render_template("agents/coding.md.tmpl"),
                tools=["exec"],
                sandbox_mode="local-unsafe",
                spawn=[],
                skills=list(skills),
                primary=False,
            ),
        ]
    else:
        plans = [
            _AgentPlan(
                agent_id=agent_id,
                instructions=render_template("agents/basic.md.tmpl"),
                tools=[],
                sandbox_mode="disabled",
                spawn=[],
                skills=list(skills),
                primary=True,
            )
        ]
    if agent_id != "main" and all(plan.agent_id != "main" for plan in plans):
        plans.append(
            _AgentPlan(
                agent_id="main",
                instructions=render_template("agents/default-main.md.tmpl", primary_agent_id=agent_id),
                tools=[],
                sandbox_mode="disabled",
                spawn=[agent_id],
                skills=[],
                primary=False,
            )
        )
    return plans


def _base_url_override(kind: str, base_url: str | None) -> str | None:
    if base_url is None or not base_url.strip():
        return None
    value = base_url.strip()
    spec = get_provider_spec(kind)
    if value.rstrip("/") == spec.default_base_url.rstrip("/"):
        return None
    return value


def _render_anyagent_yaml(
    *,
    provider_key: str,
    provider_registered: bool,
    model_name: str | None,
    base_url: str | None,
) -> str:
    document: dict[str, Any] = {}
    models: dict[str, Any] = {}
    default = _models_default(
        provider_key=provider_key,
        provider_registered=provider_registered,
        model_name=model_name,
    )
    if default is not None:
        models["default"] = default
    provider_override = _provider_override(
        provider_key=provider_key,
        provider_registered=provider_registered,
        base_url=base_url,
    )
    if provider_override:
        models["providers"] = {provider_key: provider_override}
    if models:
        document["models"] = models
    header: list[str] = []
    if default is not None and default.endswith(":") and default.split(":", 1)[1] == "":
        header.append("# No model id was provided. Replace models.default with provider:model-id.")
    return dump_yaml_with_header(header, document, ANYAGENT_SCHEMA_LINE)


def _models_default(*, provider_key: str, provider_registered: bool, model_name: str | None) -> str | None:
    # openai + gpt-4o-mini is the built-in `fast` alias. Omit it.
    if provider_registered and provider_key == _BUILTIN_PROVIDER and model_name in {None, _BUILTIN_MODEL}:
        return None
    if model_name:
        return f"{provider_key}:{model_name}"
    if not provider_registered or provider_key != _BUILTIN_PROVIDER:
        return f"{provider_key}:"
    return None


def _provider_override(*, provider_key: str, provider_registered: bool, base_url: str | None) -> dict[str, Any]:
    if provider_registered:
        if base_url is None:
            return {}
        return {"base_url": base_url}
    # A name that is not a built-in provider must be declared or `provider:model`
    # is read as a single model id. The key stays an environment placeholder.
    override: dict[str, Any] = {"kind": "openai", "api_key": "${OPENAI_API_KEY}"}
    if base_url is not None:
        override["base_url"] = base_url
    return override
