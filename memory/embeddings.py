"""Budgeted OpenAI-compatible embedding calls, with a local content-addressed cache."""

import hashlib
import json
import os
import sqlite3
from pathlib import Path

import httpx
import numpy as np

from core.budget import Budget


class EmbeddingClient:
    def __init__(self, model: str, budget: Budget, cache_path: Path):
        self.model, self.budget = model, budget
        self.base = os.getenv("EMBEDDING_BASE_URL") or os.getenv("LLM_BASE_URL", "")
        self.key = os.getenv("EMBEDDING_API_KEY") or os.getenv("LLM_API_KEY")
        if not self.base or not self.key:
            raise ValueError(
                "Embedding API configuration missing; configure endpoint/key or explicitly choose local embeddings"
            )
        self.cache_path = Path(cache_path)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.cache_path) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS vectors (id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )

    def embed(self, texts: list[str]) -> np.ndarray:
        texts = [t[:4000] for t in texts]
        ids = [
            hashlib.sha256((self.base + self.model + ":1024:" + t).encode()).hexdigest()
            for t in texts
        ]
        vectors = {}
        with sqlite3.connect(self.cache_path) as db:
            for key in dict.fromkeys(ids):
                row = db.execute("SELECT payload FROM vectors WHERE id=?", (key,)).fetchone()
                if row:
                    vectors[key] = json.loads(row[0])
        missing = list(dict.fromkeys(key for key in ids if key not in vectors))
        by_id = dict(zip(ids, texts, strict=True))
        for start in range(0, len(missing), 10):
            keys = missing[start : start + 10]
            batch = [by_id[key] for key in keys]
            self.budget.reserve("embedding", sum(len(t.encode()) for t in batch) + 512)
            try:
                response = httpx.post(
                    self.base.rstrip("/") + "/embeddings",
                    headers={"Authorization": f"Bearer {self.key}"},
                    json={
                        "model": self.model,
                        "input": batch,
                        "dimensions": 1024,
                        "encoding_format": "float",
                    },
                    timeout=60,
                )
                response.raise_for_status()
                payload = response.json()
                rows = sorted(payload["data"], key=lambda r: r["index"])
                if [r["index"] for r in rows] != list(range(len(batch))):
                    raise ValueError("Embedding result indices mismatch")
                array = np.asarray([r["embedding"] for r in rows], dtype="float32")
                if (
                    array.shape != (len(batch), 1024)
                    or not np.isfinite(array).all()
                    or (np.linalg.norm(array, axis=1) == 0).any()
                ):
                    raise ValueError("Invalid embedding vectors")
                array /= np.linalg.norm(array, axis=1, keepdims=True)
                self.budget.embedding_tokens += payload.get("usage", {}).get("total_tokens", 0)
                with sqlite3.connect(self.cache_path) as db:
                    for key, row in zip(keys, array.tolist(), strict=True):
                        vectors[key] = row
                        db.execute(
                            "INSERT OR REPLACE INTO vectors VALUES (?,?)", (key, json.dumps(row))
                        )
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
                raise RuntimeError(
                    f"Embedding request failed ({type(exc).__name__}); no silent lexical fallback"
                ) from None
        return np.asarray([vectors[key] for key in ids], dtype="float32")
