"""Read-only SQL tool used by the data specialist.

Deliberately restricted to SELECT statements — the data specialist should
never be able to mutate the demo database, so this is enforced here rather
than trusted to prompt instructions.
"""
from __future__ import annotations

import re

from sqlalchemy import text

from app.db.session import get_engine

_SELECT_RE = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
_FORBIDDEN_RE = re.compile(r"\b(insert|update|delete|drop|alter|create|attach|pragma)\b", re.IGNORECASE)
_MAX_ROWS = 200


def run_query(sql: str, params: dict | None = None) -> dict:
    if not _SELECT_RE.match(sql):
        raise ValueError("only SELECT (or WITH ... SELECT) statements are allowed")
    if _FORBIDDEN_RE.search(sql):
        raise ValueError("query contains a disallowed keyword")

    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text(sql), params or {})
        rows = result.mappings().fetchmany(_MAX_ROWS)
        return {
            "columns": list(rows[0].keys()) if rows else list(result.keys()),
            "rows": [dict(r) for r in rows],
            "truncated": len(rows) == _MAX_ROWS,
        }
