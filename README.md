# AgentFoundry

A multi-agent orchestration platform: a **supervisor** plans a goal into a dependency-DAG of
subtasks and delegates each to a **specialist** agent (API, database, or sandboxed-code tools), a
**reviewer** validates every result before it's accepted, and a **human-in-the-loop** queue steps
in whenever confidence is low, a result keeps failing review, or a subtask is inherently
sensitive. Everything is traced, costed, retried, and checkpointed so a crash never means
re-doing finished work.

## Architecture

```
            ┌─────────────────────────────────────────────────────────────┐
            │                         FastAPI (app/main.py)                │
            │   POST /tasks   GET /tasks/{id}   POST /approvals/{id}/decide│
            └───────────────────────────┬─────────────────────────────────┘
                                         │ enqueues
                                         ▼
                              Celery worker (app/workers)
                     automatic retries, exponential backoff, jitter
                                         │ run_graph(task)
                                         ▼
  ┌──────────────────────────────────────────────────────────────────────┐
  │                 LangGraph `step` node (self-loop)                     │
  │                                                                       │
  │   1. SUPERVISOR plans goal -> Subtask DAG (+ confidence score)        │
  │        reads long-term memory (ChromaDB) for this user's past tasks  │
  │   2. plan-confidence gate  ──low──> human APPROVE_PLAN                │
  │   3. pick next ready subtask (app/orchestrator/dag.py topological     │
  │      scheduler — only subtasks whose deps are COMPLETED are ready)    │
  │   4. sensitive-op gate (code exec) ──> human APPROVE_ACTION           │
  │   5. SPECIALIST runs (api_agent / data_agent / code_agent) via the    │
  │      ToolRegistry (tracing + rate limiting on every call)            │
  │   6. REVIEWER scores the result (0-1) + feedback                      │
  │   7. score ok -> COMPLETED · score low & attempts left -> retry       │
  │      score low & attempts exhausted -> human APPROVE_ACTION           │
  │   8. all subtasks COMPLETED -> SUPERVISOR synthesizes final answer,   │
  │      writes an episodic memory for next time                         │
  │                                                                       │
  │   Every return saves the Task to Redis first → that's the checkpoint. │
  └──────────────────────────────────────────────────────────────────────┘
                                         │
              ┌──────────────────────────┼──────────────────────────┐
              ▼                          ▼                          ▼
         Redis                     ChromaDB                  OpenTelemetry
   working memory, task/       long-term memory:         spans for every agent
   approval checkpoints,       past tasks, importance     decision + tool call:
   Celery broker/backend,      scoring, decay-based        latency, cost, success/
   tool rate limits            consolidation/expiry        failure, retries
```

### Human-in-the-loop levels

| Level            | Trigger                                                              |
|------------------|-----------------------------------------------------------------------|
| `NOTIFY`         | A subtask is auto-retried after a low review score (fyi, non-blocking) |
| `APPROVE_ACTION` | A single sensitive subtask (sandboxed code execution) or a subtask that exhausted its retries |
| `APPROVE_PLAN`   | The supervisor's whole plan has confidence below `PLAN_CONFIDENCE_THRESHOLD` |
| `TAKE_OVER`      | A human calls `POST /tasks/{id}/escalate` to pause automation entirely |

### Checkpointing & retries

The `Task` document (subtasks + their status/result/attempts) is the single source of truth,
persisted to Redis after **every** step the graph takes — not just at the end of a run. A Celery
task failure triggers an automatic retry with exponential backoff (`autoretry_for`,
`retry_backoff`); the retry calls `run_graph` again, which reloads the checkpointed `Task` and the
DAG scheduler (`app/orchestrator/dag.py::get_ready_subtasks`) only ever returns subtasks that are
still `PENDING` — anything already `COMPLETED` is never re-run.

### Observability & cost

Every agent decision and tool call is wrapped in an OpenTelemetry span (`app/observability/tracing.py`)
carrying the task id, agent, tool, attempt number, and sensitivity flag — span duration gives
latency for free. LLM calls are costed per-model from token usage (`app/observability/cost.py`).
By default spans print to the console; set `OTEL_EXPORTER_OTLP_ENDPOINT` to ship them to
Jaeger/Tempo/Honeycomb/etc.

### Sandboxed code execution

The code specialist's `run_python` tool (`app/tools/sandbox_tool.py`) is defense-in-depth, not a
full jail: a static AST check rejects dangerous imports (`os`, `subprocess`, `socket`, ...) and
dunder escape hatches before anything runs; the snippet then executes in an isolated subprocess
(`-I -S`, empty env, throwaway tmpdir) under POSIX resource limits (CPU time, address space,
process count, output size) with a wall-clock timeout as backup.

## Running it

```bash
cp .env.example .env            # defaults to LLM_PROVIDER=mock — no API keys required
docker compose up --build       # redis, api, celery worker, streamlit dashboard
python -m scripts.seed_demo_db  # populates the demo customers/orders tables
python -m scripts.demo          # creates a task, auto-approves HITL checkpoints, prints the result
```

Open the approval dashboard at `http://localhost:8501`, or drive the API directly:

```bash
curl -X POST localhost:8000/tasks -H 'content-type: application/json' \
  -d '{"user_id": "demo-user", "goal": "Pull recent orders and report a summary"}'

curl localhost:8000/approvals            # anything waiting on a human
curl -X POST localhost:8000/approvals/<id>/decide -d '{"approved": true}'
```

Set `LLM_PROVIDER=anthropic` (or `openai`) with an API key in `.env` to replace the deterministic
planning/review heuristics with real LLM calls — the graph, tools, memory, approvals, retries, and
tracing all work identically either way, which is also what makes the test suite and `mock` mode
fully offline.

## Tests

```bash
pip install -r requirements.txt
pytest
```

Covers DAG scheduling (including the "never re-run a completed subtask" guarantee), the sandbox's
static checks and timeout enforcement, the supervisor's deterministic planning heuristic, and the
Redis-backed task/approval store — all against `fakeredis`, with no external services required.

## Project layout

```
app/
  main.py                 FastAPI app
  api/routes/             tasks, approvals, memory endpoints
  orchestrator/
    graph.py              the LangGraph workflow
    supervisor.py          planning + synthesis
    reviewer.py             result validation
    escalation.py            human-in-the-loop approval helpers
    dag.py                    dependency scheduling
    specialists/              api_agent, data_agent, code_agent
  tools/                  registry (tracing + rate limits), api/db/sandbox tools
  memory/                 Redis working memory, ChromaDB long-term memory
  persistence/            Redis-backed Task/ApprovalRequest store (= the checkpoint)
  observability/          OpenTelemetry tracing, cost estimation
  workers/                Celery app + the retrying task
scripts/                  demo.py, seed_demo_db.py
streamlit_app/            human approval dashboard
tests/
```
