"""Token-based cost estimation for agent decisions and tool/LLM calls."""
from __future__ import annotations

# USD per 1M tokens, (input, output). Mock/unknown models fall back to a flat rate.
_PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-haiku-4-5": (0.80, 4.00),
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "mock": (0.0, 0.0),
}

_DEFAULT_RATE = (3.00, 15.00)


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    in_rate, out_rate = _PRICING.get(model, _DEFAULT_RATE)
    return (input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate
