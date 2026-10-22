from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM
    llm_provider: str = "mock"  # "anthropic" | "openai" | "mock"
    llm_model: str = "claude-sonnet-4-5"
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Chroma
    chroma_persist_dir: str = "./chroma_data"

    # Demo DB
    database_url: str = "sqlite:///./demo.db"

    # Celery
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # OpenTelemetry
    otel_service_name: str = "agentfoundry"
    otel_exporter_otlp_endpoint: str | None = None

    # Human-in-the-loop thresholds
    review_score_threshold: float = 0.7
    plan_confidence_threshold: float = 0.6
    max_specialist_retries: int = 2

    # Sandbox limits
    sandbox_timeout_seconds: int = 5
    sandbox_max_memory_mb: int = 128


@lru_cache
def get_settings() -> Settings:
    return Settings()
