"""Thin LLM wrapper over Anthropic/OpenAI via langchain, with token + cost accounting.

Every agent node (supervisor, specialists, reviewer) checks `settings.llm_provider`
itself: in "mock" mode they run deterministic heuristics instead of calling this
client at all, so the whole graph is exercisable offline/in CI with zero API keys.
With a real provider configured, they call `LLMClient.complete(...)`.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from app.config import Settings, get_settings
from app.observability.cost import estimate_cost_usd


@dataclass
class LLMResponse:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._chat_model = None

    def _get_chat_model(self):
        if self._chat_model is not None:
            return self._chat_model

        if self._settings.llm_provider == "anthropic":
            from langchain_anthropic import ChatAnthropic

            self._chat_model = ChatAnthropic(
                model=self._settings.llm_model,
                api_key=self._settings.anthropic_api_key,
            )
        elif self._settings.llm_provider == "openai":
            from langchain_openai import ChatOpenAI

            self._chat_model = ChatOpenAI(
                model=self._settings.llm_model,
                api_key=self._settings.openai_api_key,
            )
        else:
            raise RuntimeError(
                "LLMClient.complete() was called while llm_provider='mock'. "
                "Callers must branch to a heuristic in mock mode instead."
            )
        return self._chat_model

    def complete(self, *, system: str, prompt: str) -> LLMResponse:
        model = self._get_chat_model()
        result = model.invoke(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ]
        )
        usage = getattr(result, "usage_metadata", None) or {}
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        return LLMResponse(
            text=result.content if isinstance(result.content, str) else str(result.content),
            model=self._settings.llm_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=estimate_cost_usd(self._settings.llm_model, input_tokens, output_tokens),
        )


@lru_cache
def get_llm_client() -> LLMClient:
    return LLMClient(get_settings())
