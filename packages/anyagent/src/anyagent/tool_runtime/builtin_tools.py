from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from anyagent.protocol.credential_vault import CredentialScope
from anyagent.server.sandbox import EXEC_TOOL, SandboxManager, build_exec_handler
from anyagent.server.security.credential_backends import CredentialStore
from anyagent.tool_runtime.models import ToolDefinition
from anyagent.tool_runtime.registry import ToolRegistry


logger = logging.getLogger("anyagent.tool_runtime")


def _credential_headers_from_context(context: dict[str, Any]) -> dict[str, str]:
    """Extract outbound HTTP headers from tool context `_credentials` mapping."""
    raw = context.get("_credentials")
    if not isinstance(raw, dict):
        return {}

    headers: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key.startswith("header:"):
            continue
        header_name = key.removeprefix("header:").strip()
        if not header_name or not isinstance(value, str) or not value.strip():
            continue
        headers[header_name] = value.strip()
    return headers


def _credential_value_from_context(context: dict[str, Any], target: str) -> str | None:
    """Read one credential-derived value from tool context `_credentials` mapping."""
    raw = context.get("_credentials")
    if not isinstance(raw, dict):
        return None
    value = raw.get(target)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _normalize_tavily_results(payload: dict[str, Any], *, query: str, max_results: int) -> dict[str, Any]:
    """Normalize Tavily Search API payload into a compact AnyAgent result."""
    results_raw = payload.get("results")
    results: list[dict[str, Any]] = []
    if isinstance(results_raw, list):
        for item in results_raw[:max_results]:
            if not isinstance(item, dict):
                continue
            normalized = {
                "title": item.get("title"),
                "url": item.get("url"),
                "content": item.get("content"),
                "score": item.get("score"),
            }
            results.append({k: v for k, v in normalized.items() if v is not None})
    out = {
        "provider": "tavily",
        "query": query,
        "answer": payload.get("answer"),
        "results": results,
    }
    return {k: v for k, v in out.items() if v is not None}


def _normalize_serpapi_results(payload: dict[str, Any], *, query: str, max_results: int, engine: str) -> dict[str, Any]:
    """Normalize SerpApi payload into a compact AnyAgent result."""
    results_raw = payload.get("organic_results")
    results: list[dict[str, Any]] = []
    if isinstance(results_raw, list):
        for item in results_raw[:max_results]:
            if not isinstance(item, dict):
                continue
            normalized = {
                "title": item.get("title"),
                "url": item.get("link"),
                "content": item.get("snippet"),
                "position": item.get("position"),
            }
            results.append({k: v for k, v in normalized.items() if v is not None})
    out = {
        "provider": "serpapi",
        "engine": engine,
        "query": query,
        "results": results,
    }
    answer_box = payload.get("answer_box")
    if isinstance(answer_box, dict):
        answer = answer_box.get("answer") or answer_box.get("snippet")
        if answer is not None:
            out["answer"] = answer
    return {k: v for k, v in out.items() if v is not None}


def register_builtin_core_tools_sync(registry: ToolRegistry) -> None:
    """
    Register framework-owned built-in core tools.

    The sync implementation lets in-process runtimes register built-ins during
    construction, while the async wrapper below preserves the historical apps API.
    """

    async def web_fetch(args: dict[str, Any], context: dict[str, Any]) -> str:
        url = args["url"]
        timeout_ms = int(args.get("timeout_ms", 15000))

        # SSRF baseline: block localhost and link-local in the v0 built-in.
        if isinstance(url, str) and (
            url.startswith("http://127.")
            or url.startswith("http://localhost")
            or url.startswith("http://169.254.")
            or url.startswith("https://127.")
            or url.startswith("https://localhost")
        ):
            raise ValueError("forbidden url")

        outbound_headers = {"user-agent": "anyagent/0", **_credential_headers_from_context(context)}

        async with httpx.AsyncClient(timeout=timeout_ms / 1000.0, follow_redirects=True) as client:
            r = await client.get(url, headers=outbound_headers)
            return json.dumps(
                {
                    "status": r.status_code,
                    "headers": dict(list(r.headers.items())[:50]),
                    "text": r.text,
                    "url": str(r.url),
                },
                ensure_ascii=False,
            )

    registry.register_tool(
        tool=ToolDefinition(
            name="core.web_fetch",
            description="Fetch a URL and return text content (SSRF-protected, limited).",
            category="core",
            parameters={
                "type": "object",
                "additionalProperties": False,
                "required": ["url"],
                "properties": {
                    "url": {"type": "string"},
                    "timeout_ms": {"type": "integer", "minimum": 1000, "maximum": 60000},
                },
            },
            credentials=[
                {
                    "ref_kind": "bearer_token",
                    "injection_target": "header:Authorization",
                    "format": "Bearer {value}",
                    "required": False,
                    "description": "Optional bearer token used when fetching authenticated URLs.",
                }
            ],
        ),
        handler=web_fetch,
    )

    async def web_search(args: dict[str, Any], context: dict[str, Any]) -> str:
        query = str(args["q"]).strip()
        provider = str(args.get("provider") or "tavily").strip().lower()
        max_results = int(args.get("max_results", 5))
        timeout_ms = int(args.get("timeout_ms", 15000))
        if not query:
            raise ValueError("q is required")

        api_key = _credential_value_from_context(context, "secret:api_key")
        if api_key is None:
            raise ValueError("missing search API credential")

        if provider == "tavily":
            from tavily import AsyncTavilyClient

            request_body: dict[str, Any] = {"query": query, "max_results": max_results}
            topic = args.get("topic")
            if isinstance(topic, str) and topic.strip():
                request_body["topic"] = topic.strip()
            client = AsyncTavilyClient(api_key=api_key)
            payload = await client.search(timeout=timeout_ms / 1000.0, **request_body)
            return json.dumps(_normalize_tavily_results(payload, query=query, max_results=max_results), ensure_ascii=False)

        if provider == "serpapi":
            engine = str(args.get("engine") or "google").strip() or "google"
            request_params = {
                "engine": engine,
                "q": query,
                "num": max_results,
                "api_key": api_key,
            }
            async with httpx.AsyncClient(timeout=timeout_ms / 1000.0, follow_redirects=True) as client:
                response = await client.get(
                    "https://serpapi.com/search.json",
                    headers={"User-Agent": "anyagent/0"},
                    params=request_params,
                )
                response.raise_for_status()
                payload = response.json()
            return json.dumps(
                _normalize_serpapi_results(payload, query=query, max_results=max_results, engine=engine),
                ensure_ascii=False,
            )

        raise ValueError(f"unsupported search provider: {provider}")

    registry.register_tool(
        tool=ToolDefinition(
            name="core.web_search",
            description="Search the web via provider-backed search APIs and return normalized results.",
            category="core",
            parameters={
                "type": "object",
                "additionalProperties": False,
                "required": ["q"],
                "properties": {
                    "q": {"type": "string", "minLength": 1},
                    "provider": {"type": "string", "enum": ["tavily", "serpapi"]},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
                    "timeout_ms": {"type": "integer", "minimum": 1000, "maximum": 60000},
                    "topic": {"type": "string", "enum": ["general", "news"]},
                    "engine": {"type": "string"},
                },
            },
            credentials=[
                {
                    "ref_kind": "api_key",
                    "injection_target": "secret:api_key",
                    "format": "{value}",
                    "required": True,
                    "description": "Search provider API key used by core.web_search.",
                }
            ],
        ),
        handler=web_search,
    )


async def register_builtin_core_tools(registry: ToolRegistry) -> None:
    register_builtin_core_tools_sync(registry)


def register_sandbox_exec_tool(
    registry: ToolRegistry,
    *,
    sandbox_manager: SandboxManager,
    sandbox_policy_for_agent: Any,
) -> None:
    registry.register_tool(
        tool=EXEC_TOOL,
        handler=build_exec_handler(
            sandbox_manager=sandbox_manager,
            sandbox_policy_for_agent=sandbox_policy_for_agent,
        ),
    )


def register_privileged_core_tools_sync(*, registry: ToolRegistry, credential_store: CredentialStore) -> None:
    """
    Register privileged core tools that require explicit allowlist in policy.

    These tools are dangerous by nature (write-only credential ops) and must never be
    enabled by default. Policy enforcement is handled by the manifest/request policy.
    """

    async def credential_set(args: dict[str, Any], context: dict[str, Any]) -> str:
        credential_id = args["credential_id"]
        kind = args["kind"]
        value = args["value"]

        scope_raw = args.get("scope")
        agent_id = context.get("agent_id") if isinstance(context.get("agent_id"), str) else None
        if scope_raw is None:
            if agent_id:
                scope = CredentialScope(level="agent", agent_id=agent_id)
            else:
                scope = CredentialScope(level="global")
        else:
            scope = CredentialScope.model_validate(scope_raw)

        metadata = args.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be an object")

        await credential_store.set(
            credential_id=str(credential_id).strip(),
            kind=str(kind).strip(),
            value=str(value),
            scope=scope,
            metadata=dict(metadata),
        )

        logger.info(
            "credential_agent.set",
            extra={
                "audit_ref": context.get("_audit_ref"),
                "actor": f"agent:{agent_id}" if agent_id else "agent:unknown",
                "operation": "set",
                "credential_id": str(credential_id).strip(),
                "kind": str(kind).strip(),
                "scope_level": scope.level,
                "scope_agent_id": scope.agent_id,
            },
        )

        return json.dumps(
            {
                "ok": True,
                "credential_id": str(credential_id).strip(),
                "kind": str(kind).strip(),
                "scope": scope.model_dump(exclude_none=True),
                "metadata": dict(metadata),
            },
            ensure_ascii=False,
        )

    registry.register_tool(
        tool=ToolDefinition(
            name="admin.credential_set",
            description="Privileged: write-only set credential (no get). Requires explicit allowlist.",
            category="core",
            parameters={
                "type": "object",
                "additionalProperties": False,
                "required": ["credential_id", "kind", "value"],
                "properties": {
                    "credential_id": {"type": "string", "minLength": 1},
                    "kind": {"type": "string", "minLength": 1},
                    "value": {"type": "string", "minLength": 1},
                    "scope": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["level"],
                        "properties": {
                            "level": {"type": "string", "enum": ["global", "agent"]},
                            "agent_id": {"type": "string"},
                        },
                    },
                    "metadata": {"type": "object"},
                },
            },
        ),
        handler=credential_set,
    )


async def register_privileged_core_tools(*, registry: ToolRegistry, credential_store: CredentialStore) -> None:
    register_privileged_core_tools_sync(registry=registry, credential_store=credential_store)
