"""Redis-backed working memory, scoped to a single task.

Holds short-lived state a running task needs across subtasks (intermediate
notes, extracted facts, tool outputs worth remembering) that does not belong
in the long-term vector store. Expires on its own via TTL so it never
outlives the task.
"""
from __future__ import annotations

import json

import redis

from app.config import get_settings

_TTL_SECONDS = 24 * 60 * 60


class WorkingMemory:
    def __init__(self, task_id: str, client: redis.Redis | None = None) -> None:
        settings = get_settings()
        self._task_id = task_id
        self._r = client or redis.Redis.from_url(settings.redis_url, decode_responses=True)
        self._kv_key = f"memory:working:{task_id}"
        self._events_key = f"memory:events:{task_id}"

    def set(self, key: str, value: object) -> None:
        self._r.hset(self._kv_key, key, json.dumps(value))
        self._r.expire(self._kv_key, _TTL_SECONDS)

    def get(self, key: str, default: object = None) -> object:
        raw = self._r.hget(self._kv_key, key)
        return json.loads(raw) if raw is not None else default

    def get_all(self) -> dict:
        return {k: json.loads(v) for k, v in self._r.hgetall(self._kv_key).items()}

    def append_event(self, event: dict) -> None:
        self._r.rpush(self._events_key, json.dumps(event))
        self._r.expire(self._events_key, _TTL_SECONDS)

    def get_events(self) -> list[dict]:
        return [json.loads(e) for e in self._r.lrange(self._events_key, 0, -1)]

    def clear(self) -> None:
        self._r.delete(self._kv_key, self._events_key)
