from __future__ import annotations

import logging
from typing import Any

from anyagent.env import getenv

_LOGGER = logging.getLogger(__name__)

_PROVIDER: Any | None = None
_CONFIGURED = False


def otlp_endpoint() -> str | None:
    value = getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def otlp_headers() -> dict[str, str]:
    raw = ""
    value = getenv("OTEL_EXPORTER_OTLP_HEADERS")
    if isinstance(value, str) and value.strip():
        raw = value.strip()
    if not raw:
        return {}
    headers: dict[str, str] = {}
    if raw.startswith("{"):
        try:
            import json

            obj = json.loads(raw)
        except Exception:
            return {}
        if isinstance(obj, dict):
            for key, value in obj.items():
                if isinstance(key, str) and isinstance(value, str) and key.strip():
                    headers[key.strip()] = value
        return headers
    for item in raw.split(","):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        if key.strip() and value.strip():
            headers[key.strip()] = value.strip()
    return headers


def get_tracer_provider(*, tracer_provider: Any | None = None) -> Any | None:
    """Return an OTel TracerProvider when export is configured; otherwise None (zero export)."""

    if tracer_provider is not None:
        return tracer_provider
    endpoint = otlp_endpoint()
    if not endpoint:
        return None
    return _ensure_otlp_provider(endpoint)


def _ensure_otlp_provider(endpoint: str) -> Any | None:
    global _PROVIDER, _CONFIGURED
    if _CONFIGURED:
        return _PROVIDER
    _CONFIGURED = True
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        _LOGGER.warning("anyagent[otel] is not installed; OTLP tracing disabled")
        return None
    provider = TracerProvider(resource=Resource.create({"service.name": "anyagent"}))
    exporter = OTLPSpanExporter(endpoint=endpoint, headers=otlp_headers() or None)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    _PROVIDER = provider
    return provider


def reset_otel_for_tests() -> None:
    global _PROVIDER, _CONFIGURED
    _PROVIDER = None
    _CONFIGURED = False


def build_instrumentation_capabilities(
    *,
    agent_id: str,
    session_key: str | None,
    response_id: str | None,
    tracer_provider: Any | None = None,
) -> list[Any]:
    provider = get_tracer_provider(tracer_provider=tracer_provider)
    if provider is None:
        return []
    from pydantic_ai.capabilities import Hooks, Instrumentation
    from pydantic_ai.models.instrumented import InstrumentationSettings

    settings = InstrumentationSettings(tracer_provider=provider)
    hooks = Hooks(id="anyagent-span-attrs")

    @hooks.on.before_run
    async def _set_span_attributes(ctx: Any) -> None:
        try:
            from opentelemetry import trace
        except ImportError:
            return
        span = trace.get_current_span()
        if span is None:
            return
        if session_key:
            span.set_attribute("session.id", session_key)
            span.set_attribute("langfuse.session.id", session_key)
            span.set_attribute("session_key", session_key)
        span.set_attribute("agent_id", agent_id)
        run_id = response_id or getattr(ctx, "run_id", None)
        if isinstance(run_id, str) and run_id:
            span.set_attribute("response.id", run_id)
            span.set_attribute("run.id", run_id)

    return [Instrumentation(settings=settings), hooks]
