"""ChromaDB-backed long-term memory: past tasks, approaches, and preferences.

The supervisor queries this during planning so a user's prior corrections and
successful strategies inform the next plan, instead of every task starting
from zero. Importance scores decay with age; `consolidate()` prunes memories
that have decayed past a usefulness floor (expiration) rather than letting
the store grow unbounded.

Embeddings: if an OpenAI key is configured we use real OpenAI embeddings;
otherwise we fall back to a deterministic hashing embedding so the whole
pipeline — including semantic-ish recall — works fully offline/in CI.
"""
from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone
from functools import lru_cache

import chromadb

from app.config import get_settings
from app.models.schemas import MemoryRecord

_HASH_DIM = 256
_MIN_IMPORTANCE = 0.05
_DECAY_PER_DAY = 0.98


class _HashingEmbeddingFunction:
    """Deterministic, dependency-free embedding for offline/demo use.

    Hashes each token into one of `_HASH_DIM` buckets (a signed hashing
    trick, à la feature hashing) and L2-normalizes. Not semantically rich,
    but stable, fast, and good enough to demo similarity search without a
    network call or a bundled ML model.
    """

    def __call__(self, input: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in input]

    @staticmethod
    def _embed(text: str) -> list[float]:
        vec = [0.0] * _HASH_DIM
        for token in text.lower().split():
            digest = hashlib.sha256(token.encode()).hexdigest()
            bucket = int(digest[:8], 16) % _HASH_DIM
            sign = 1.0 if int(digest[8:9], 16) % 2 == 0 else -1.0
            vec[bucket] += sign
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


def _build_embedding_function():
    settings = get_settings()
    if settings.openai_api_key:
        from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction

        return OpenAIEmbeddingFunction(api_key=settings.openai_api_key, model_name="text-embedding-3-small")
    return _HashingEmbeddingFunction()


class LongTermMemory:
    def __init__(self) -> None:
        settings = get_settings()
        self._client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
        self._collection = self._client.get_or_create_collection(
            name="agent_memory", embedding_function=_build_embedding_function()
        )

    def add(self, record: MemoryRecord) -> None:
        self._collection.upsert(
            ids=[record.id],
            documents=[record.text],
            metadatas=[
                {
                    "user_id": record.user_id,
                    "task_id": record.task_id or "",
                    "kind": record.kind,
                    "importance": record.importance,
                    "created_at": record.created_at.isoformat(),
                }
            ],
        )

    def query(self, user_id: str, query_text: str, top_k: int = 5) -> list[dict]:
        result = self._collection.query(
            query_texts=[query_text],
            n_results=top_k,
            where={"user_id": user_id},
        )
        out = []
        ids = result.get("ids", [[]])[0]
        docs = result.get("documents", [[]])[0]
        metas = result.get("metadatas", [[]])[0]
        dists = result.get("distances", [[]])[0]
        for i, doc, meta, dist in zip(ids, docs, metas, dists):
            out.append({"id": i, "text": doc, "distance": dist, **meta})
        return out

    def list_for_user(self, user_id: str, limit: int = 50) -> list[dict]:
        result = self._collection.get(where={"user_id": user_id}, limit=limit)
        return [
            {"id": i, "text": doc, **meta}
            for i, doc, meta in zip(result["ids"], result["documents"], result["metadatas"])
        ]

    def delete(self, record_id: str) -> None:
        self._collection.delete(ids=[record_id])

    def consolidate(self, user_id: str) -> dict:
        """Decay importance by age, then expire anything below the floor."""
        records = self.list_for_user(user_id, limit=1000)
        now = datetime.now(timezone.utc)
        decayed, expired = 0, 0
        for r in records:
            created = datetime.fromisoformat(r["created_at"])
            age_days = max((now - created).total_seconds() / 86400, 0.0)
            new_importance = r["importance"] * (_DECAY_PER_DAY ** age_days)
            if new_importance < _MIN_IMPORTANCE:
                self.delete(r["id"])
                expired += 1
            else:
                self._collection.update(ids=[r["id"]], metadatas=[{**{k: v for k, v in r.items() if k not in ("id", "text")}, "importance": new_importance}])
                decayed += 1
        return {"decayed": decayed, "expired": expired}


@lru_cache
def get_long_term_memory() -> LongTermMemory:
    return LongTermMemory()
