"""
Gateway webhook 路由挂载。

将 GatewayRegistry 中注册的 webhook 路由动态挂载到 FastAPI。
每个 connector 插件注册的 webhook route 会变成实际的 HTTP endpoint。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from anyagent.gateway.connector_contracts import (
    ConnectorWebhookAuth,
    OutboundDeliveryError,
    WebhookAuthError,
    WebhookAuthSuccess,
)
from anyagent.gateway.plugins import WebhookRoute
from anyagent.protocol.tool_runtime import AuthRef

_LOGGER = logging.getLogger(__name__)


def create_gateway_webhook_router(state: Any) -> APIRouter:
    """
    从 GatewayRegistry 动态创建 FastAPI router。

    遍历 state.gateway_registry.webhook_routes，
    为每个 WebhookRoute 创建对应的 HTTP endpoint。
    """
    router = APIRouter()

    for route in state.gateway_registry.webhook_routes:
        _mount_webhook_route(router, route, state)

    return router


def _mount_webhook_route(router: APIRouter, route: WebhookRoute, state: Any) -> None:
    """将单个 WebhookRoute 挂载到 FastAPI router。"""

    path = route.path
    methods = route.methods
    handler = route.handler

    # 查找关联的 connector（通过 path 匹配）
    connector = _find_connector_by_webhook(state, route)

    async def _webhook_endpoint(req: Request) -> JSONResponse:
        try:
            raw_body = await req.body()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="invalid request body") from exc

        headers: dict[str, str] = {}
        for key, value in req.headers.items():
            headers[key.lower()] = value

        auth_result = None
        # 1. Webhook 签名验证
        if connector is not None and hasattr(connector, "webhook_auth") and connector.webhook_auth is not None:
            try:
                auth_result = await _verify_webhook_auth(
                    auth=connector.webhook_auth,
                    headers=headers,
                    raw_body=raw_body,
                    state=state,
                    connector=connector,
                )
            except WebhookAuthError as exc:
                raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

        # 2. 调用 connector handler
        try:
            result = handler(
                request=req,
                headers=headers,
                raw_body=raw_body,
                verified_auth=auth_result,
                state=state,
                connector=connector,
            )
            # 支持 async handler
            import asyncio
            if asyncio.iscoroutine(result):
                result = await result
        except WebhookAuthError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        except OutboundDeliveryError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        except Exception as exc:
            _LOGGER.exception("webhook handler error: path=%s error=%s", path, exc)
            raise HTTPException(status_code=500, detail="internal webhook handler error") from exc

        if isinstance(result, dict):
            return JSONResponse(result)
        if result is None:
            return JSONResponse({"ok": True})
        return JSONResponse({"ok": True, "data": result})

    # 为每个 method 注册路由
    for method in methods:
        if method.upper() == "POST":
            router.add_api_route(
                path=path,
                endpoint=_webhook_endpoint,
                methods=["POST"],
                name=f"gateway_webhook_{_route_slug(path)}",
            )
        elif method.upper() == "GET":
            router.add_api_route(
                path=path,
                endpoint=_webhook_endpoint,
                methods=["GET"],
                name=f"gateway_webhook_{_route_slug(path)}",
            )
        elif method.upper() == "PUT":
            router.add_api_route(
                path=path,
                endpoint=_webhook_endpoint,
                methods=["PUT"],
                name=f"gateway_webhook_{_route_slug(path)}",
            )


async def _verify_webhook_auth(
    *,
    auth: ConnectorWebhookAuth,
    headers: dict[str, str],
    raw_body: bytes,
    state: Any,
    connector: Any,
) -> WebhookAuthSuccess:
    """
    验证 webhook 签名（connector 统一入口）。

    密钥从 Credential Vault 解析（credential_id → secret）。
    """
    secret_ref = _resolve_webhook_secret_ref(connector)
    if secret_ref is None:
        # Fallback: 直接读 connector 上的 webhook_secret（仅开发环境）
        secret = getattr(connector, "webhook_secret", None) or ""
        if not secret:
            raise WebhookAuthError("webhook secret not configured", status_code=500)
    else:
        # 从 Credential Vault 解析
        try:
            secret = await state.credentials.resolve(
                auth_ref=secret_ref,
                scope_context=None,
            )
        except Exception as exc:
            _LOGGER.warning(
                "credential resolve failed: credential_id=%s kind=%s error=%s",
                secret_ref.ref,
                secret_ref.kind,
                exc,
            )
            raise WebhookAuthError("webhook secret resolve failed", status_code=500) from exc

        if not secret:
            raise WebhookAuthError("webhook secret not found in credential vault", status_code=500)

    try:
        return await auth.verify(headers=headers, raw_body=raw_body, secret=secret)
    except WebhookAuthError:
        raise
    except Exception as exc:
        _LOGGER.exception("webhook auth verify error: %s", exc)
        raise WebhookAuthError("webhook signature verification failed", status_code=403) from exc


def _find_connector_by_webhook(state: Any, route: WebhookRoute) -> Any:
    """
    根据 webhook route 查找对应的 connector。

    遍历 gateway_registry 中所有 channel connector，
    返回匹配的 connector（path 前缀匹配或在 connector 的 webhook_routes 中）。
    """
    registry = state.gateway_registry
    if isinstance(route.channel, str):
        connector = registry.channel_connectors.get(route.channel.strip())
        if connector is not None:
            return connector
    for channel, connector in registry.channel_connectors.items():
        connector_routes = getattr(connector, "webhook_routes", None)
        if connector_routes and route in connector_routes:
            return connector
        # 按 path 前缀模糊匹配
        channel_prefix = f"/gateway/{channel}"
        route_prefix = f"/{channel}"
        if route.path.startswith(channel_prefix) or route.path.startswith(route_prefix):
            return connector
    return None


def _resolve_webhook_secret_ref(connector: Any) -> AuthRef | None:
    auth_ref = getattr(connector, "webhook_secret_auth_ref", None)
    if isinstance(auth_ref, AuthRef):
        return auth_ref
    if isinstance(auth_ref, dict):
        try:
            return AuthRef.model_validate(auth_ref)
        except Exception:
            return None

    credential_id = getattr(connector, "webhook_secret_credential_id", None)
    if not isinstance(credential_id, str) or not credential_id.strip():
        return None

    credential_kind = getattr(connector, "webhook_secret_kind", None)
    if not isinstance(credential_kind, str) or not credential_kind.strip():
        credential_kind = "secret"
    return AuthRef(kind=credential_kind, ref=credential_id.strip())


def _route_slug(path: str) -> str:
    """生成路由名称 slug。"""
    return path.strip("/").replace("/", "_").replace("-", "_").replace(".", "_")
