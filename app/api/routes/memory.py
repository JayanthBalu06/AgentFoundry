from __future__ import annotations

from fastapi import APIRouter

from app.memory.long_term_memory import get_long_term_memory

router = APIRouter(prefix="/memory", tags=["memory"])


@router.get("/{user_id}")
def list_memory(user_id: str, limit: int = 50) -> list[dict]:
    return get_long_term_memory().list_for_user(user_id, limit=limit)


@router.delete("/{user_id}/{record_id}")
def delete_memory(user_id: str, record_id: str) -> dict:
    get_long_term_memory().delete(record_id)
    return {"deleted": record_id}


@router.post("/{user_id}/consolidate")
def consolidate_memory(user_id: str) -> dict:
    return get_long_term_memory().consolidate(user_id)
