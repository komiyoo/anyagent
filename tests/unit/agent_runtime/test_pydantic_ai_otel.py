from __future__ import annotations

import asyncio
from typing import Any

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.settings import ModelSettings

from anyagent.agent_runtime.loop.otel import build_instrumentation_capabilities, otlp_endpoint, reset_otel_for_tests
from anyagent.agent_runtime.tool_loop import run_tool_loop_nonstream
from anyagent.protocol.openai_responses import AnyAgentFunctionToolParam
from anyagent.protocol.tool_runtime import ExecuteMeta, ExecuteResponseCompleted, ManifestResponse, ToolContext


class _ToolRuntime:
    async def manifest(self, req: Any) -> ManifestResponse:
        _ = req
        return ManifestResponse(
            tools=[
                AnyAgentFunctionToolParam(
                    type="function",
                    name="demo.lookup",
                    description="lookup",
                    parameters={"type": "object", "properties": {}},
                )
            ],
            toolset_version=1,
        )

    async def execute(self, req: Any) -> ExecuteResponseCompleted:
        _ = req
        return ExecuteResponseCompleted(status="completed", output="ok", meta=ExecuteMeta())


class _ToolThenTextModel(Model):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    @property
    def model_name(self) -> str:
        return "otel-test"

    @property
    def system(self) -> str:
        return "test"

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        _ = messages, model_settings, model_request_parameters
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                parts=[ToolCallPart(tool_name="demo_lookup", args={}, tool_call_id="call_1")],
                model_name=self.model_name,
            )
        return ModelResponse(parts=[TextPart(content="done")], model_name=self.model_name)


def test_no_endpoint_skips_instrumentation(monkeypatch) -> None:
    reset_otel_for_tests()
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert otlp_endpoint() is None
    caps = build_instrumentation_capabilities(agent_id="main", session_key="s", response_id="r")
    assert caps == []


def test_tool_calling_run_emits_generation_span_with_session_attrs() -> None:
    asyncio.run(_run_tool_calling_run_emits_generation_span_with_session_attrs())


async def _run_tool_calling_run_emits_generation_span_with_session_attrs() -> None:
    reset_otel_for_tests()
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    status, payload = await run_tool_loop_nonstream(
        model_provider=_ToolThenTextModel(),
        tool_runtime=_ToolRuntime(),  # type: ignore[arg-type]
        agent_id="main",
        session_key="sess-otel",
        body={"model": "gpt-test", "input": "hello"},
        idempotency_key=None,
        tool_context=ToolContext(),
        canonical_response_id="resp_otel_1",
        tracer_provider=provider,
    )
    assert status == 200, payload
    spans = exporter.get_finished_spans()
    assert spans, "expected at least one OTel span"
    names = {span.name for span in spans}
    generation = [span for span in spans if "chat" in span.name.lower() or "model" in span.name.lower() or "generation" in span.name.lower() or span.name == "agent run"]
    if not generation:
        generation = list(spans)
    attrs: dict[str, Any] = {}
    for span in spans:
        attrs.update(dict(span.attributes or {}))
    assert "sess-otel" in {attrs.get("session.id"), attrs.get("session_key"), attrs.get("langfuse.session.id")} or any(
        value == "sess-otel" for value in attrs.values()
    ), (names, attrs)
    assert "main" in {attrs.get("agent_id")} or any(value == "main" for value in attrs.values()), attrs
    assert "resp_otel_1" in {attrs.get("response.id"), attrs.get("run.id")} or any(
        value == "resp_otel_1" for value in attrs.values()
    ), attrs
