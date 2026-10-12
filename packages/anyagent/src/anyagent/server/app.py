import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from anyagent.config.agents import (
    ANYAGENT_CONFIG_DIR,
    load_agent_catalog,
    stat_config_mtimes,
)
from anyagent.config.loader import EffectiveConfig, load_effective_config
from anyagent.gateway.plugins import GatewayRegistry
from anyagent.gateway.sequencer import KeyedSequencer
from anyagent.gateway.tooling import register_gateway_tools
from anyagent.mcp.manager import MCPManagerRegistry
from anyagent.observability import _parse_header_env, emit_observability_event, get_observability_emitter
from anyagent.protocol.alerts import AlertChannel
from anyagent.server.app_builders import (
    _build_opensandbox_backend_if_needed,
    _load_gateway_plugins,
    _parse_cors_origins,
    _resolve_plugin_roots,
    _safe_error_message,
)
from anyagent.server.app_state import AnyAgentServerApp
from anyagent.server.config.settings import resolve_server_storage
from anyagent.server.persistence.alerts import AlertEvaluator, InMemoryAlertStore, default_alert_rules
from anyagent.server.persistence.evaluations import JsonEvaluationStore
from anyagent.server.persistence.manifest_cache import ManifestCache
from anyagent.server.persistence.prompt_versions import JsonPromptVersionStore
from anyagent.server.persistence.runs import RunRegistry
from anyagent.server.persistence.storage_backends import ServerStorageBundle, build_server_storage_bundle
from anyagent.server.persistence.telemetry_store import (
    InMemoryObservabilityEventSink,
    InMemoryTelemetryEventStore,
    PostgresTelemetryEventStore,
    RunEventTelemetryStore,
    TelemetryObservabilitySink,
)
from anyagent.server.routes.admin import create_admin_router
from anyagent.server.routes.internal_agents import create_internal_agents_router
from anyagent.server.routes.internal_events import create_builtin_internal_events_router
from anyagent.server.routes.internal_evaluations import create_internal_evaluations_router
from anyagent.server.routes.internal_observability import create_internal_observability_router
from anyagent.server.routes.internal_prompt import create_internal_prompt_router
from anyagent.server.routes.internal_responses import create_internal_responses_router
from anyagent.server.routes.internal_skills import create_builtin_internal_skills_router
from anyagent.server.routes.internal_tools import create_internal_tools_router
from anyagent.server.routes.gateway_webhooks import create_gateway_webhook_router
from anyagent.server.routes.responses import create_responses_router
from anyagent.server.routes.system import create_system_router
from anyagent.server.runtime.in_process import InProcessToolRuntimeService
from anyagent.server.runtime.lock_service import RedisSessionLockClient, build_session_lock_service
from anyagent.server.runtime.workspace_env import hydrate_workspace_runtime_environment
from anyagent.server.sandbox import SandboxManager
from anyagent.server.security.credential_runtime import open_process_credential_store


def create_app(
    *,
    workspace_dir: str | Path,
    config: EffectiveConfig | None = None,
    cli_overrides: dict[str, Any] | None = None,
    session_config_overrides: dict[str, Any] | None = None,
) -> FastAPI:
    workspace = Path(workspace_dir).expanduser().resolve()
    effective = config or load_effective_config(workspace, cli_overrides=cli_overrides)
    hydration = hydrate_workspace_runtime_environment(effective)
    if any(record.applied for record in hydration):
        effective = load_effective_config(workspace, cli_overrides=effective.cli_overrides)
    storage_settings, resolved_storage = resolve_server_storage(effective.storage)
    catalog = load_agent_catalog(workspace_dir=workspace, session_config_overrides=session_config_overrides)
    if not any(pack.spec.exposed for pack in catalog.packs.values()):
        raise RuntimeError("workspace must define at least one exposed agent")
    opensandbox_backend = _build_opensandbox_backend_if_needed(catalog, effective.sandbox)
    sandbox_manager = SandboxManager(root_dir=effective.server.sandbox_root, opensandbox_backend=opensandbox_backend)
    credential_store = open_process_credential_store(effective.credentials, workspace_dir=workspace)
    storage_bundle: ServerStorageBundle = build_server_storage_bundle(
        event_store_backend=resolved_storage.event_store_backend,
        run_store_backend=resolved_storage.run_store_backend,
        session_store_backend=resolved_storage.session_store_backend,
        storage_settings=storage_settings,
    )
    observability_event_sink = InMemoryObservabilityEventSink()
    if resolved_storage.storage_profile in {"postgres", "postgres-redis"} and storage_settings.effective_postgres_dsn is not None:
        telemetry_event_store: Any = PostgresTelemetryEventStore(
            postgres_dsn=str(storage_settings.effective_postgres_dsn),
            postgres_schema=storage_settings.postgres_schema,
            schema_policy=storage_settings.postgres_schema_policy,
        )
    else:
        telemetry_event_store = InMemoryTelemetryEventStore()
    telemetry_observability_sink = TelemetryObservabilitySink(telemetry_events=telemetry_event_store)
    telemetry_store = RunEventTelemetryStore(
        event_store=storage_bundle.event_store,
        run_store=storage_bundle.run_store,
        observability_events=observability_event_sink,
        telemetry_events=telemetry_event_store,
        include_observability_sink_events=False,
    )
    alert_rules = default_alert_rules()
    alert_webhook_channel = _build_alert_webhook_channel(effective)
    if alert_webhook_channel is not None:
        webhook_rule_ids = {"builtin.server_error", "builtin.quota_exhausted"}
        alert_rules = [
            rule.model_copy(update={"channels": [*rule.channels, alert_webhook_channel]})
            if rule.rule_id in webhook_rule_ids
            else rule
            for rule in alert_rules
        ]
    alert_store = InMemoryAlertStore(rules=alert_rules)
    alert_evaluator = AlertEvaluator(telemetry_store=telemetry_store, alert_store=alert_store)
    evaluation_store = JsonEvaluationStore(path=workspace / ANYAGENT_CONFIG_DIR / "evaluations.json")
    prompt_version_store = JsonPromptVersionStore(path=workspace / ANYAGENT_CONFIG_DIR / "prompt_versions.json")
    runtime = InProcessToolRuntimeService(
        workspace_dir=str(workspace),
        catalog=catalog,
        sandbox_manager=sandbox_manager,
        credential_store=credential_store,
    )
    gateway_registry = GatewayRegistry()
    resolved_plugin_roots = _resolve_plugin_roots(effective.plugins.roots or None, workspace=workspace)
    loaded_plugins, plugin_errors, loaded_plugin_catalog = _load_gateway_plugins(
        runtime=runtime,
        roots=resolved_plugin_roots,
        fail_open=effective.plugins.fail_open,
        gateway_registry=gateway_registry,
    )
    state = AnyAgentServerApp(
        workspace_dir=workspace,
        catalog=catalog,
        config=effective,
        resolved_storage=resolved_storage,
        storage_settings=storage_settings,
        events=storage_bundle.event_store,
        credentials=credential_store,
        mcp_credentials=credential_store,
        sandbox_manager=sandbox_manager,
        runtime=runtime,
        mcp_managers=MCPManagerRegistry(),
        runs=RunRegistry(),
        manifest_cache=ManifestCache(ttl_seconds=2.0),
        run_store=storage_bundle.run_store,
        session_store=storage_bundle.session_store,
        telemetry_store=telemetry_store,
        alert_store=alert_store,
        alert_evaluator=alert_evaluator,
        evaluation_store=evaluation_store,
        prompt_version_store=prompt_version_store,
        observability_event_sink=observability_event_sink,
        telemetry_event_store=telemetry_event_store,
        telemetry_observability_sink=telemetry_observability_sink,
        session_sequencer=KeyedSequencer(),
        session_lock_service=_build_session_lock_service(resolved_storage.session_lock_backend, storage_settings),
        session_lease_ttl_s=resolved_storage.session_lease_ttl_s,
        storage_resources=storage_bundle.resources,
        plugin_roots=resolved_plugin_roots,
        loaded_plugins=loaded_plugins,
        loaded_plugin_catalog=loaded_plugin_catalog,
        plugin_errors=plugin_errors,
        gateway_registry=gateway_registry,
        api_key=_non_empty(effective.server.api_key),
        admin_api_key=_non_empty(effective.server.admin_api_key),
        session_config_overrides=session_config_overrides,
        config_mtimes=stat_config_mtimes(workspace, session_config_overrides),
    )
    register_gateway_tools(registry=state.runtime._registry, gateway_registry=gateway_registry)
    @asynccontextmanager
    async def _lifespan(_app: FastAPI):
        _app.state.anyagent = state
        get_observability_emitter().add_sink(state.observability_event_sink)
        get_observability_emitter().add_sink(state.telemetry_observability_sink)
        state.alert_evaluator.start()
        try:
            yield
        finally:
            await state.alert_evaluator.stop()
            get_observability_emitter().remove_sink(state.telemetry_observability_sink)
            get_observability_emitter().remove_sink(state.observability_event_sink)
            await state.mcp_managers.cleanup_all()
            telemetry_closer = getattr(state.telemetry_event_store, "dispose", None)
            if callable(telemetry_closer):
                result = telemetry_closer()
                if asyncio.iscoroutine(result):
                    await result
            for resource in state.storage_resources:
                closer = getattr(resource, "dispose", None) or getattr(resource, "aclose", None) or getattr(resource, "close", None)
                if callable(closer):
                    result = closer()
                    if asyncio.iscoroutine(result):
                        await result

    app = FastAPI(title="anyagent", version="0.4.30", lifespan=_lifespan)
    if effective.server.enable_studio:
        resolved_studio_dir: Path | None = None
        if effective.server.studio_dir:
            resolved_studio_dir = Path(effective.server.studio_dir)
        if resolved_studio_dir is not None:
            if not resolved_studio_dir.is_dir():
                raise RuntimeError(f"Studio directory does not exist: {resolved_studio_dir}")
            @app.get("/", include_in_schema=False)
            async def root_studio_redirect() -> RedirectResponse:
                return RedirectResponse(url="/studio/")

            @app.get("/studio", include_in_schema=False)
            async def studio_index() -> FileResponse:
                return FileResponse(resolved_studio_dir / "index.html")

            app.mount("/studio", StaticFiles(directory=str(resolved_studio_dir), html=True), name="studio")
    parsed_cors_origins = _parse_cors_origins(effective.server.cors_origins)
    if parsed_cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=parsed_cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["authorization", "content-type", "idempotency-key", "x-agent-id"],
        )
    app.state.anyagent = state
    app.state.runtime_env_hydration = hydration
    app.include_router(create_admin_router())
    app.include_router(create_system_router())
    app.include_router(create_internal_agents_router())
    app.include_router(create_builtin_internal_events_router())
    app.include_router(create_internal_evaluations_router())
    app.include_router(create_internal_observability_router())
    app.include_router(create_internal_prompt_router())
    app.include_router(create_internal_responses_router())
    app.include_router(create_builtin_internal_skills_router())
    app.include_router(create_internal_tools_router())
    app.include_router(create_responses_router())

    # 挂载 Gateway webhook 路由（由 connector 插件注册）
    if state.gateway_registry.webhook_routes:
        app.include_router(
            create_gateway_webhook_router(state),
            prefix="/gateway",
            tags=["gateway-webhooks"],
        )

    @app.middleware("http")
    async def _config_hot_reload_middleware(request: Request, call_next: Any) -> Any:
        await state.refresh_config_if_needed()
        return await call_next(request)

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        # FastAPI/Starlette route HTTPException and RequestValidationError to
        # their own dedicated handlers (matched earlier in the MRO), so this
        # only catches genuinely unhandled exceptions. Emit an error
        # observability event so the alert pipeline can notify operators.
        emit_observability_event(
            "server.unhandled_exception",
            category="server",
            level="error",
            payload={
                "error_type": type(exc).__name__,
                "message": _safe_error_message(exc),
                "path": request.url.path,
                "method": request.method,
            },
        )
        return JSONResponse(
            status_code=500,
            content={"error": {"type": "server_error", "message": "internal server error"}},
        )

    return app


def _non_empty(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _build_session_lock_service(backend: str, storage_settings: Any):
    """Build the session lock from explicit storage settings.

    A redis backend receives a client built from those settings, so the lock
    service does not reload the process environment.
    """

    if backend == "redis":
        if storage_settings.redis_dsn is None:
            raise RuntimeError("SESSION_LOCK_BACKEND=redis requires REDIS_DSN")
        return build_session_lock_service(
            backend="redis",
            client=RedisSessionLockClient(
                redis_dsn=str(storage_settings.redis_dsn),
                namespace=storage_settings.redis_namespace,
            ),
        )
    return build_session_lock_service(backend=backend)  # type: ignore[arg-type]


def _build_alert_webhook_channel(config: EffectiveConfig) -> AlertChannel | None:
    """Build the alert webhook channel from config. Returns None when no URL is set."""

    url = (config.alerts.webhook_url or "").strip()
    if not url:
        return None
    fmt = (config.alerts.webhook_format or "json").strip().lower() or "json"
    if fmt not in {"json", "feishu"}:
        fmt = "json"
    headers = _parse_header_env(config.alerts.webhook_headers or "")
    return AlertChannel(kind="webhook", url=url, headers=headers, format=fmt)
