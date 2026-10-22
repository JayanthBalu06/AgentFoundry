"""OpenTelemetry wiring.

Every agent decision, tool call, retry, and failure is wrapped in a span via
`traced_step`. Span duration gives latency for free; `cost_usd` and other
attributes are attached explicitly so a trace backend (or the console
exporter, by default) can break down a task by where time and money went.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)
from opentelemetry.trace import Status, StatusCode

from app.config import get_settings

log = logging.getLogger("agentfoundry.tracing")

_initialized = False


def init_tracing() -> None:
    global _initialized
    if _initialized:
        return
    settings = get_settings()
    resource = Resource.create({SERVICE_NAME: settings.otel_service_name})
    provider = TracerProvider(resource=resource)

    if settings.otel_exporter_otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))
    else:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    _initialized = True


def get_tracer() -> trace.Tracer:
    init_tracing()
    return trace.get_tracer("agentfoundry")


@contextmanager
def traced_step(
    name: str,
    *,
    task_id: str | None = None,
    agent: str | None = None,
    tool: str | None = None,
    **attributes: str | int | float | bool,
) -> Iterator[trace.Span]:
    """Wrap one agent decision or tool call. Records latency, attrs, and failures."""
    tracer = get_tracer()
    with tracer.start_as_current_span(name) as span:
        if task_id:
            span.set_attribute("agentfoundry.task_id", task_id)
        if agent:
            span.set_attribute("agentfoundry.agent", agent)
        if tool:
            span.set_attribute("agentfoundry.tool", tool)
        for key, value in attributes.items():
            span.set_attribute(f"agentfoundry.{key}", value)
        try:
            yield span
        except Exception as exc:  # noqa: BLE001 - re-raised after recording
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            span.record_exception(exc)
            raise
