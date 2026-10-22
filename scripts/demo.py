"""End-to-end demo: submit a goal, watch the supervisor plan + delegate,
auto-approve any human-in-the-loop checkpoints as they appear, and print the
final synthesized result.

Prerequisites: `docker compose up` (or the API + a Celery worker + Redis
running some other way) on API_BASE_URL (default http://localhost:8000).
Run with: python -m scripts.demo
"""
from __future__ import annotations

import os
import time

import httpx

BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
GOAL = "Pull recent order data, compute summary stats, and report the result."
TERMINAL_STATUSES = {"completed", "failed"}


def main() -> None:
    client = httpx.Client(base_url=BASE_URL, timeout=30.0)

    client.get("/health").raise_for_status()
    print("API is healthy.")

    task = client.post("/tasks", json={"user_id": "demo-user", "goal": GOAL}).json()
    task_id = task["id"]
    print(f"Created task {task_id}: {GOAL!r}")

    deadline = time.monotonic() + 90
    seen_approvals: set[str] = set()

    while time.monotonic() < deadline:
        task = client.get(f"/tasks/{task_id}").json()
        status = task["status"]
        print(f"  status={status}")

        if status == "awaiting_approval":
            approvals = client.get(f"/tasks/{task_id}/approvals").json()
            for approval in approvals:
                if approval["decided"] or approval["id"] in seen_approvals:
                    continue
                seen_approvals.add(approval["id"])
                print(f"  [human-in-the-loop] {approval['level']} — {approval['summary']}")
                print("  auto-approving for this demo...")
                client.post(
                    f"/approvals/{approval['id']}/decide",
                    json={"approved": True, "note": "auto-approved by scripts/demo.py"},
                )

        if status in TERMINAL_STATUSES:
            break
        time.sleep(1.5)

    print("\n--- Final task ---")
    print(f"status: {task['status']}")
    for s in task["subtasks"]:
        print(f"  [{s['specialist']:4}] {s['title']} -> {s['status']} (score={s.get('review_score')})")
    print("\nResult:\n" + (task.get("final_result") or "(none)"))


if __name__ == "__main__":
    main()
