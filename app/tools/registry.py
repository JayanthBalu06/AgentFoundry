"""Central tool registry: every tool call flows through here.

This is the one choke point that gives us, for free, on every tool a
specialist agent invokes: an OpenTelemetry span (decision/call/latency),
a structured log line, and a per-tool rate limit backed by Redis — instead
of each tool reimplementing its own instrumentation.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable

import redis

from app.config import get_settings
from app.observability.tracing import traced_step

log = logging.getLogger("agentfoundry.tools")


class RateLimitExceeded(Exception):
    pass


@dataclass
class ToolCallResult:
    ok: bool
    output: object = None
    error: str | None = None
    latency_ms: float = 0.0


@dataclass
class _ToolSpec:
    name: str
    fn: Callable[..., object]
    sensitive: bool
    max_calls_per_minute: int


class ToolRegistry:
    def __init__(self, redis_client: redis.Redis | None = None) -> None:
        settings = get_settings()
        self._r = redis_client or redis.Redis.from_url(settings.redis_url, decode_responses=True)
        self._tools: dict[str, _ToolSpec] = {}

    def register(self, name: str, fn: Callable[..., object], *, sensitive: bool = False, max_calls_per_minute: int = 30) -> None:
        self._tools[name] = _ToolSpec(name=name, fn=fn, sensitive=sensitive, max_calls_per_minute=max_calls_per_minute)

    def is_sensitive(self, name: str) -> bool:
        return self._tools[name].sensitive

    def _check_rate_limit(self, spec: _ToolSpec) -> None:
        key = f"ratelimit:tool:{spec.name}:{int(time.time() // 60)}"
        count = self._r.incr(key)
        if count == 1:
            self._r.expire(key, 60)
        if count > spec.max_calls_per_minute:
            raise RateLimitExceeded(f"tool '{spec.name}' exceeded {spec.max_calls_per_minute} calls/min")

    def call(self, name: str, *, agent: str, task_id: str, **kwargs: object) -> ToolCallResult:
        if name not in self._tools:
            return ToolCallResult(ok=False, error=f"unknown tool '{name}'")
        spec = self._tools[name]
        started = time.monotonic()
        try:
            self._check_rate_limit(spec)
            with traced_step(
                f"tool.{name}",
                task_id=task_id,
                agent=agent,
                tool=name,
                sensitive=spec.sensitive,
            ):
                output = spec.fn(**kwargs)
            latency_ms = (time.monotonic() - started) * 1000
            log.info("tool_call ok tool=%s agent=%s task=%s latency_ms=%.1f", name, agent, task_id, latency_ms)
            return ToolCallResult(ok=True, output=output, latency_ms=latency_ms)
        except Exception as exc:  # noqa: BLE001 - tool failures are data, not crashes
            latency_ms = (time.monotonic() - started) * 1000
            log.warning("tool_call failed tool=%s agent=%s task=%s error=%s", name, agent, task_id, exc)
            return ToolCallResult(ok=False, error=str(exc), latency_ms=latency_ms)


_registry: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
        _register_default_tools(_registry)
    return _registry


def _register_default_tools(registry: ToolRegistry) -> None:
    from app.tools.api_tool import call_api
    from app.tools.db_tool import run_query
    from app.tools.sandbox_tool import run_python

    registry.register("api_call", call_api, sensitive=False, max_calls_per_minute=60)
    registry.register("db_query", run_query, sensitive=False, max_calls_per_minute=60)
    registry.register("run_python", run_python, sensitive=True, max_calls_per_minute=20)
