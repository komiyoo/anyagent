from __future__ import annotations

"""Offline smoke for AnyAgent client sync/async entry semantics."""

import asyncio
from unittest.mock import patch

from anyagent import AnyAgent
from anyagent.agent_api_client import Admin, Agents, Prompts, Responses
from anyagent.protocol.admin_storage import StorageHealthResponse
from anyagent.protocol.agent_api_internal import InternalAgentDetailResponse, InternalAgentsListResponse, InternalPromptBundlePreviewResponse
from anyagent.protocol.credential_vault import AdminCredentialListResponse, AdminCredentialRef
from anyagent.protocol.health import HealthResponse
from anyagent.protocol.openai_responses import build_minimal_openai_response_json


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    """Validate cached OpenAI entrypoints and explicit factory semantics."""

    client = AnyAgent(api_key="test-key", base_url="http://127.0.0.1:8787/")

    sync_1 = client.openai
    sync_2 = client.openai
    _assert(sync_1 is sync_2, "`client.openai` should cache one sync SDK client")
    _assert(str(sync_1.base_url).rstrip("/") == "http://127.0.0.1:8787/v1", "sync base_url mismatch")

    async_1 = client.async_openai
    async_2 = client.async_openai
    _assert(async_1 is async_2, "`client.async_openai` should cache one async SDK client")
    _assert(str(async_1.base_url).rstrip("/") == "http://127.0.0.1:8787/v1", "async base_url mismatch")

    sync_new = client.as_openai_client()
    async_new = client.as_async_openai_client()
    _assert(sync_new is not sync_1, "`as_openai_client()` should return a fresh sync SDK client")
    _assert(async_new is not async_1, "`as_async_openai_client()` should return a fresh async SDK client")

    client_v1 = AnyAgent(api_key="test-key", base_url="http://127.0.0.1:8787/v1")
    _assert(
        str(client_v1.openai.base_url).rstrip("/") == "http://127.0.0.1:8787/v1",
        "pre-normalized /v1 base_url should not duplicate suffix",
    )

    async def _fake_health(self: AnyAgent) -> HealthResponse:
        _ = self
        return HealthResponse(ok=True, workspace="/example-workspace", agent_ids=["main"])

    with patch.object(AnyAgent, "health", _fake_health):
        health = asyncio.run(client.health())
        _assert(health.agent_ids == ["main"], "`client.health()` should parse typed health payload")

    async def _fake_retrieve_valid(self: Responses, response_id: str) -> dict:
        return build_minimal_openai_response_json(response_id=response_id, status="completed")

    async def _fake_retrieve_invalid(self: Responses, response_id: str) -> dict:
        return {"oops": response_id}

    with patch.object(Responses, "retrieve", _fake_retrieve_valid):
        typed = asyncio.run(client.responses.retrieve_typed("resp_typed_ok"))
        _assert(getattr(typed, "id", None) == "resp_typed_ok", "`retrieve_typed` should decode valid Response payload")

    with patch.object(Responses, "retrieve", _fake_retrieve_invalid):
        typed_none = asyncio.run(client.responses.retrieve_typed("resp_typed_bad"))
        _assert(typed_none is None, "`retrieve_typed` should return None for invalid payload")

    async def _fake_storage_health(self: Admin) -> StorageHealthResponse:
        return StorageHealthResponse.model_validate({
            "ok": True,
            "storage_mode": "external",
            "backends": {
                "event_store": "external",
                "run_store": "external",
                "session_store": "external",
                "session_lock": "redis",
            },
            "retention_s": {"events": 7200, "runs": 7200, "sessions": 86400},
            "stores": {"session_store": {"type": "CachedSessionStore", "layers": ["PostgresSessionStore", "RedisSessionStore"]}},
            "capabilities": {
                "session_store": {
                    "tier": "external",
                    "long_term_owner": "anyagent-apps",
                    "source_of_truth": "postgres+redis",
                    "requires_services": ["postgres", "redis"],
                    "restart_recovery": True,
                    "cross_instance": True,
                    "supports_snapshot_cas": True,
                }
            },
            "postgres": {"configured": True, "reachable": True, "schema": "public"},
            "redis": {"configured": True, "reachable": True, "namespace": "anyagent"},
        })

    with patch.object(Admin, "storage_health", _fake_storage_health):
        health = asyncio.run(client.admin.storage_health())
        _assert(health.ok is True, "`client.admin.storage_health()` should parse typed payload")
        _assert(health.backends.session_lock == "redis", "storage health backend parsing mismatch")
        _assert(health.capabilities["session_store"].tier == "external", "storage capability parsing mismatch")

    async def _fake_set_credential(self: Admin, request) -> AdminCredentialRef:
        _ = self, request
        return AdminCredentialRef.model_validate(
            {
                "credential_id": "search_api_key",
                "kind": "api_key",
                "scope": {"level": "agent", "agent_id": "main"},
                "metadata": {"provider": "search"},
            }
        )

    async def _fake_list_credentials(self: Admin) -> AdminCredentialListResponse:
        _ = self
        return AdminCredentialListResponse.model_validate(
            {
                "credentials": [
                    {
                        "credential_id": "search_api_key",
                        "kind": "api_key",
                        "scope": {"level": "agent", "agent_id": "main"},
                        "metadata": {"provider": "search"},
                    }
                ]
            }
        )

    async def _fake_delete_credential(self: Admin, credential_id: str) -> dict:
        _ = self
        return {"ok": True, "deleted": credential_id == "search_api_key", "credential_id": credential_id}

    with (
        patch.object(Admin, "set_credential", _fake_set_credential),
        patch.object(Admin, "list_credentials", _fake_list_credentials),
        patch.object(Admin, "delete_credential", _fake_delete_credential),
    ):
        cred = asyncio.run(
            client.admin.set_credential(
                {
                    "credential_id": "search_api_key",
                    "kind": "api_key",
                    "value": "secret",
                    "scope": {"level": "agent", "agent_id": "main"},
                }
            )
        )
        _assert(cred.scope.agent_id == "main", "`client.admin.set_credential()` should parse typed ref")
        creds = asyncio.run(client.admin.list_credentials())
        _assert(creds.credentials[0].credential_id == "search_api_key", "`client.admin.list_credentials()` parsing mismatch")
        deleted = asyncio.run(client.admin.delete_credential("search_api_key"))
        _assert(deleted["deleted"] is True and deleted["credential_id"] == "search_api_key", "`client.admin.delete_credential()` delete payload mismatch")

    async def _fake_agents_list(self: Agents, *, include_unexposed: bool = False) -> InternalAgentsListResponse:
        _ = self, include_unexposed
        return InternalAgentsListResponse.model_validate(
            {
                "agents": [
                    {
                        "agent_id": "main",
                        "name": "main",
                        "exposed": True,
                        "root_dir": "/example-workspace/.anyagent/agents/main",
                        "prompt_sha256": "prompt-sha",
                        "sandbox_mode": "local-unsafe",
                        "requested_tool_names": ["exec"],
                        "spawn_allow_agent_ids": ["researcher"],
                        "has_mcp": True,
                        "mcp_server_labels": ["github"],
                    }
                ]
            }
        )

    async def _fake_agent_get(self: Agents, agent_id: str, *, include_prompt: bool = False) -> InternalAgentDetailResponse:
        _ = self, include_prompt
        return InternalAgentDetailResponse.model_validate(
            {
                "agent_id": agent_id,
                "name": agent_id,
                "exposed": True,
                "root_dir": f"/example-workspace/.anyagent/agents/{agent_id}",
                "agents_md": {
                    "path": f"/example-workspace/.anyagent/agents/{agent_id}/AGENTS.md",
                    "sha256": "prompt-sha",
                    "preview": "你是 main agent。",
                },
                "tools": {"requested_tool_names": ["exec"]},
                "skills": {"default_selected": []},
                "sandbox": {"mode": "local-unsafe"},
                "multiagent": {"spawn_allow_agent_ids": ["researcher"]},
                "mcp": {"configured": True, "server_labels": ["github"]},
            }
        )

    with patch.object(Agents, "list", _fake_agents_list), patch.object(Agents, "get", _fake_agent_get):
        agents = asyncio.run(client.agents.list())
        _assert(agents.agents[0].agent_id == "main", "`client.agents.list()` should parse typed catalog")
        _assert(agents.agents[0].spawn_allow_agent_ids == ["researcher"], "agent spawn allowlist parsing mismatch")
        agent_detail = asyncio.run(client.agents.get("main"))
        _assert(agent_detail.agents_md.text is None, "`client.agents.get()` should not require prompt text")
        _assert(agent_detail.mcp.server_labels == ["github"], "agent detail MCP parsing mismatch")

    async def _fake_prompt_preview(self: Prompts, request_body: dict, *, x_agent_id: str | None = None) -> InternalPromptBundlePreviewResponse:
        _ = request_body, x_agent_id
        return InternalPromptBundlePreviewResponse.model_validate(
            {
                "agent_id": "main",
                "session_key": "sess-preview",
                "model": "gpt-5",
                "prompt_cache_key": "cache-preview",
                "instruction_role": "developer",
                "selected_skill_ids": [],
                "manifest_tool_names": ["exec"],
                "mcp_servers": ["github"],
                "tool_context": {"trace": {"trace_id": "trace-preview"}},
                "prompt_context": {
                    "prompt_cache_key": "cache-preview",
                    "fragments": [{"kind": "agents_instructions", "cache_class": "stable_prefix"}],
                    "fragment_count": 1,
                    "retained_fragment_count": 1,
                    "stable_prefix_count": 1,
                    "contextual_count": 0,
                    "dynamic_count": 0,
                    "fragment_kinds": ["agents_instructions"],
                    "compacted": False,
                },
                "rendered_fragments": [
                    {
                        "kind": "sandbox_guidance",
                        "role": "developer",
                        "cache_class": "stable_prefix",
                        "rendered_text": "<sandbox_guidance>\n<exec_tool>exec</exec_tool>\n</sandbox_guidance>",
                    }
                ],
                "effective_body": {"input": [{"role": "user", "content": "hello"}]},
                "applied_body": {
                    "input": [
                        {"role": "developer", "content": "<sandbox_guidance>\n<exec_tool>exec</exec_tool>\n</sandbox_guidance>"},
                        {"role": "user", "content": "hello"},
                    ]
                },
            }
        )

    with patch.object(Prompts, "preview", _fake_prompt_preview):
        preview = asyncio.run(client.prompts.preview({"model": "gpt-5", "input": "hello"}))
        _assert(preview.prompt_cache_key == "cache-preview", "`client.prompts.preview()` cache key mismatch")
        _assert("exec" in preview.manifest_tool_names, "`client.prompts.preview()` manifest tool parsing mismatch")
        _assert(preview.rendered_fragments[0].kind == "sandbox_guidance", "`client.prompts.preview()` fragment parsing mismatch")

    example_bundle = client.prompts.example_run_bundle()
    _assert(example_bundle.prompt_bundle.prompt_cache_key is not None, "`client.prompts.example_run_bundle()` cache key missing")
    _assert("exec" in example_bundle.prompt_bundle.manifest_tool_names, "`client.prompts.example_run_bundle()` manifest tool names mismatch")
    _assert(any(item.kind == "sandbox_guidance" for item in example_bundle.prompt_bundle.rendered_fragments), "missing sandbox guidance fragment")
    _assert(any(item.kind == "mcp_server_ref" for item in example_bundle.prompt_bundle.rendered_fragments), "missing mcp ref fragment")
    _assert(len(example_bundle.tool_loop_items) >= 3, "example run bundle should include tool loop items")
    _assert(any(event.type == "anyagent.tool.planned" for event in example_bundle.stage_events), "missing tool planned event")
    _assert(any(event.type == "anyagent.model.stream_event" for event in example_bundle.stage_events), "missing model stream event")
    _assert(example_bundle.scenario == "sandbox_file_write", "default example scenario mismatch")
    _assert(len(example_bundle.explanation.steps) >= 3, "example run bundle explanation steps missing")

    retry_bundle = client.prompts.example_run_bundle(scenario="toolset_retry")
    _assert(retry_bundle.scenario == "toolset_retry", "toolset retry scenario mismatch")
    _assert("manifest" in retry_bundle.explanation.why_this_shape.lower(), "toolset retry explanation mismatch")
    _assert(any("retried" in str(item.item) for item in retry_bundle.tool_loop_items), "toolset retry loop item mismatch")

    scenarios = client.prompts.example_scenarios()
    _assert(len(scenarios) >= 3, "expected built-in prompt example scenarios")
    _assert(any(item.scenario == "multi_skill_research" for item in scenarios), "missing research scenario descriptor")

    no_mcp_bundle = client.prompts.example_run_bundle(
        scenario="multi_skill_research",
        options={"include_mcp": False, "skill_count": 1, "sandbox_mode": "disabled"},
    )
    _assert(no_mcp_bundle.options.include_mcp is False, "options should be reflected in response")
    _assert(no_mcp_bundle.prompt_bundle.mcp_servers == [], "mcp servers should be removed by option override")
    _assert(len(no_mcp_bundle.prompt_bundle.selected_skill_ids) == 1, "skill count override mismatch")
    _assert("exec" not in no_mcp_bundle.prompt_bundle.manifest_tool_names, "disabled sandbox should remove exec")
    _assert(
        not any(item.kind == "sandbox_guidance" for item in no_mcp_bundle.prompt_bundle.rendered_fragments),
        "disabled sandbox should remove sandbox guidance",
    )

    print("ok: acceptance_anyagent_client_surface_smoke")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
