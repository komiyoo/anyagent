from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

from anyagent.tool_runtime.models import ToolCredentialSpec, ToolDefinition


@dataclass(frozen=True)
class _TenantAuthConfig:
    tenant_access_token_env: str | None
    app_id_env: str | None
    app_secret_env: str | None


_TOKEN_CACHE: dict[tuple[str, str], tuple[str, float]] = {}


def _pick_tenant_key(context: dict[str, Any]) -> str:
    tenant_id = context.get("tenant_id")
    if isinstance(tenant_id, str) and tenant_id.strip():
        return tenant_id.strip()
    return "default"


def _get_tenant_auth(config: dict[str, Any], tenant_key: str) -> _TenantAuthConfig:
    tenants = config.get("tenants")
    if not isinstance(tenants, dict) or not tenants:
        raise ValueError("feishu plugin config must include non-empty 'tenants'")

    raw = tenants.get(tenant_key) or tenants.get("default")
    if not isinstance(raw, dict):
        raise ValueError(f"feishu plugin config missing tenant entry: {tenant_key}")

    return _TenantAuthConfig(
        tenant_access_token_env=raw.get("tenant_access_token_env"),
        app_id_env=raw.get("app_id_env"),
        app_secret_env=raw.get("app_secret_env"),
    )


def _read_env(name: str | None) -> str | None:
    if not isinstance(name, str) or not name.strip():
        return None
    v = os.getenv(name.strip())
    if not v or not v.strip():
        return None
    return v.strip()


def _base_url(config: dict[str, Any]) -> str:
    base = config.get("base_url") or "https://open.feishu.cn"
    if not isinstance(base, str) or not base.startswith("https://"):
        raise ValueError("feishu config.base_url must be https://...")
    # 基线：限制到官方域名，避免被滥用成 SSRF
    if not (base.startswith("https://open.feishu.cn") or base.startswith("https://open.larksuite.com")):
        raise ValueError("feishu config.base_url must be open.feishu.cn or open.larksuite.com")
    return base.rstrip("/")


def _timeout_ms(config: dict[str, Any]) -> int:
    t = config.get("timeout_ms", 15000)
    if not isinstance(t, int) or t < 1000 or t > 60000:
        raise ValueError("feishu config.timeout_ms must be 1000..60000")
    return t


async def _fetch_tenant_access_token(*, base_url: str, timeout_ms: int, app_id: str, app_secret: str) -> tuple[str, int]:
    url = f"{base_url}/open-apis/auth/v3/tenant_access_token/internal/"
    async with httpx.AsyncClient(timeout=timeout_ms / 1000.0, follow_redirects=True) as client:
        r = await client.post(url, json={"app_id": app_id, "app_secret": app_secret})
        data = r.json()
    if not isinstance(data, dict):
        raise ValueError("invalid feishu token response")
    if data.get("code") != 0:
        raise ValueError(f"feishu token error: {data.get('msg') or data.get('code')}")
    token = data.get("tenant_access_token")
    expire = data.get("expire")
    if not isinstance(token, str) or not token:
        raise ValueError("invalid feishu tenant_access_token")
    if not isinstance(expire, int) or expire <= 0:
        expire = 3600
    return token, expire


async def _get_bearer_token(*, config: dict[str, Any], context: dict[str, Any]) -> str:
    tenant_key = _pick_tenant_key(context)
    auth = _get_tenant_auth(config, tenant_key)

    direct = _read_env(auth.tenant_access_token_env)
    if direct:
        return direct

    app_id = _read_env(auth.app_id_env)
    app_secret = _read_env(auth.app_secret_env)
    if not app_id or not app_secret:
        raise ValueError(
            "feishu auth not configured: provide tenant_access_token_env or (app_id_env + app_secret_env) in config.json"
        )

    cache_key = (tenant_key, app_id)
    cached = _TOKEN_CACHE.get(cache_key)
    now = time.time()
    if cached and cached[1] > now + 30:
        return cached[0]

    token, expire = await _fetch_tenant_access_token(
        base_url=_base_url(config),
        timeout_ms=_timeout_ms(config),
        app_id=app_id,
        app_secret=app_secret,
    )
    _TOKEN_CACHE[cache_key] = (token, now + float(expire))
    return token


async def _get_authorization_header(*, config: dict[str, Any], context: dict[str, Any]) -> str:
    creds = context.get("_credentials")
    if isinstance(creds, dict):
        auth_header = creds.get("header:Authorization")
        if isinstance(auth_header, str) and auth_header.strip():
            return auth_header.strip()
    token = await _get_bearer_token(config=config, context=context)
    return f"Bearer {token}"


async def _get_chat_members(args: dict[str, Any], context: dict[str, Any], *, config: dict[str, Any]) -> str:
    chat_id = args["chat_id"]
    page_size = args.get("page_size")
    page_token = args.get("page_token")

    base_url = _base_url(config)
    timeout_ms = _timeout_ms(config)
    auth_header = await _get_authorization_header(config=config, context=context)

    url = f"{base_url}/open-apis/im/v1/chats/{chat_id}/members"
    params: dict[str, Any] = {}
    if page_size is not None:
        params["page_size"] = page_size
    if page_token is not None:
        params["page_token"] = page_token

    async with httpx.AsyncClient(timeout=timeout_ms / 1000.0, follow_redirects=True) as client:
        r = await client.get(url, params=params, headers={"Authorization": auth_header})
        data = r.json()
    return json.dumps(data, ensure_ascii=False)


async def _doc_create(args: dict[str, Any], context: dict[str, Any], *, config: dict[str, Any]) -> str:
    title = args["title"]
    folder_token = args["folder_token"]
    content = args.get("content")
    if content is not None and str(content).strip():
        raise ValueError("feishu.doc.create: 'content' is not supported in v0 (create only)")

    base_url = _base_url(config)
    timeout_ms = _timeout_ms(config)
    auth_header = await _get_authorization_header(config=config, context=context)

    url = f"{base_url}/open-apis/docx/v1/documents"
    async with httpx.AsyncClient(timeout=timeout_ms / 1000.0, follow_redirects=True) as client:
        r = await client.post(
            url,
            headers={"Authorization": auth_header},
            json={"title": title, "folder_token": folder_token},
        )
        data = r.json()
    return json.dumps(data, ensure_ascii=False)


async def _not_implemented(_args: dict[str, Any], _context: dict[str, Any], *, name: str) -> str:
    raise ValueError(f"{name} is not implemented yet")


def register(api) -> None:  # entrypoint
    if getattr(api, "host_kind", None) != "tool_runtime":
        return

    config = getattr(api, "config", {}) or {}

    # feishu.directory.get_chat_members
    api.registerTool(
        ToolDefinition(
            name="feishu.directory.get_chat_members",
            description="Get Feishu chat members (raw Feishu API JSON).",
            category="channel",
            credentials=[
                ToolCredentialSpec(
                    ref_kind="bearer_token",
                    injection_target="header:Authorization",
                    format="Bearer {value}",
                    required=True,
                    description="Feishu tenant access token.",
                )
            ],
            parameters={
                "type": "object",
                "additionalProperties": False,
                "required": ["chat_id"],
                "properties": {
                    "chat_id": {"type": "string"},
                    "page_size": {"type": "integer", "minimum": 1, "maximum": 200},
                    "page_token": {"type": "string"},
                },
            },
        ),
        handler=lambda args, ctx: _get_chat_members(args, ctx, config=config),
    )

    # feishu.doc.create
    api.registerTool(
        ToolDefinition(
            name="feishu.doc.create",
            description="Create a Feishu Doc (docx). Requires title + folder_token.",
            category="channel",
            credentials=[
                ToolCredentialSpec(
                    ref_kind="bearer_token",
                    injection_target="header:Authorization",
                    format="Bearer {value}",
                    required=True,
                    description="Feishu tenant access token.",
                )
            ],
            parameters={
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "folder_token"],
                "properties": {
                    "title": {"type": "string"},
                    "folder_token": {"type": "string"},
                    "content": {"type": "string"},
                },
            },
        ),
        handler=lambda args, ctx: _doc_create(args, ctx, config=config),
    )

    # placeholders to match req-6-2 target surface
    api.registerTool(
        ToolDefinition(
            name="feishu.doc.patch",
            description="Patch a Feishu Doc (placeholder; not implemented in v0 reference).",
            category="channel",
            parameters={
                "type": "object",
                "additionalProperties": False,
                "required": ["doc_id", "ops"],
                "properties": {
                    "doc_id": {"type": "string"},
                    "ops": {"type": "array"},
                },
            },
        ),
        handler=lambda args, ctx: _not_implemented(args, ctx, name="feishu.doc.patch"),
    )
    api.registerTool(
        ToolDefinition(
            name="feishu.drive.upload",
            description="Upload a file to Feishu Drive (placeholder; not implemented in v0 reference).",
            category="channel",
            parameters={
                "type": "object",
                "additionalProperties": False,
                "required": ["filename", "content_base64"],
                "properties": {
                    "filename": {"type": "string"},
                    "content_base64": {"type": "string"},
                },
            },
        ),
        handler=lambda args, ctx: _not_implemented(args, ctx, name="feishu.drive.upload"),
    )
    api.registerTool(
        ToolDefinition(
            name="feishu.perm.grant",
            description="Grant permission on a Feishu doc (placeholder; not implemented in v0 reference).",
            category="channel",
            parameters={
                "type": "object",
                "additionalProperties": False,
                "required": ["doc_id", "user_id", "role"],
                "properties": {
                    "doc_id": {"type": "string"},
                    "user_id": {"type": "string"},
                    "role": {"type": "string"},
                },
            },
        ),
        handler=lambda args, ctx: _not_implemented(args, ctx, name="feishu.perm.grant"),
    )
