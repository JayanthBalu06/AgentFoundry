from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from app.api.routes import approvals, health, memory, tasks
from app.observability.tracing import init_tracing

init_tracing()

app = FastAPI(
    title="AgentFoundry",
    description="A multi-agent orchestration platform: a supervisor that plans dependency-DAGs of work, "
    "delegates to tool-using specialists, validates results with a reviewer, escalates to humans when "
    "needed, and remembers across tasks.",
    version="0.1.0",
)

app.include_router(health.router)
app.include_router(tasks.router)
app.include_router(approvals.router)
app.include_router(memory.router)

FastAPIInstrumentor.instrument_app(app)
