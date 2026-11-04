import sqlite3
from contextlib import contextmanager
from pathlib import Path

from core.schemas import CognitiveState, Evidence, SearchResult


class EvidenceStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS evidence (
                  id TEXT NOT NULL, mode TEXT NOT NULL, payload TEXT NOT NULL,
                  PRIMARY KEY(id, mode));
                CREATE TABLE IF NOT EXISTS runs (
                  id TEXT PRIMARY KEY, mode TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS snapshots (
                  run_id TEXT NOT NULL, step INTEGER NOT NULL, node TEXT NOT NULL,
                  payload TEXT NOT NULL, PRIMARY KEY(run_id, step));
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=20)
        try:
            with db:
                yield db
        finally:
            db.close()

    def save_evidence(self, evidence: list[Evidence], mode: str):
        if any(e.synthetic != (mode == "demo") for e in evidence):
            raise ValueError("Synthetic and live evidence cannot be mixed")
        with self.connection() as db:
            for e in evidence:
                # Retain the FIRST observed immutable snapshot for historical availability checks.
                db.execute(
                    "INSERT OR IGNORE INTO evidence VALUES (?, ?, ?)",
                    (e.evidence_id, mode, e.model_dump_json()),
                )

    def get(self, evidence_id: str, mode: str) -> Evidence | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT payload FROM evidence WHERE id=? AND mode=?", (evidence_id, mode)
            ).fetchone()
        return Evidence.model_validate_json(row[0]) if row else None

    def query(self, as_of, mode: str, category: str | None = None) -> list[Evidence]:
        with self.connection() as db:
            rows = db.execute("SELECT payload FROM evidence WHERE mode=?", (mode,)).fetchall()
        evidence = [Evidence.model_validate_json(r[0]) for r in rows]
        return [
            e
            for e in evidence
            if e.retrieved_at <= as_of
            and (e.published_at is None or e.published_at <= as_of)
            and (category is None or e.category == category)
        ]

    def snapshot(self, state: CognitiveState, node: str):
        with self.connection() as db:
            db.execute(
                "INSERT OR REPLACE INTO snapshots VALUES (?, ?, ?, ?)",
                (state.run_id, len(state.trace), node, state.model_dump_json()),
            )
            db.execute(
                "INSERT OR REPLACE INTO runs VALUES (?, ?, ?)",
                (state.run_id, state.mode, state.model_dump_json()),
            )

    def recent_documents(self, as_of, mode, days=7):
        """Reuse observed raw search snapshots, preserving original retrieval dates."""
        with self.connection() as db:
            rows = db.execute(
                "SELECT payload FROM snapshots WHERE node='Search' ORDER BY rowid DESC LIMIT 100"
            ).fetchall()
        unique = {}
        for row in rows:
            import json

            payload = json.loads(row[0])
            if payload["mode"] != mode:
                continue
            for item in payload["search_results"]:
                doc = SearchResult.model_validate(item)
                if 0 <= (as_of - doc.retrieved_at).total_seconds() <= days * 86400 and (
                    not doc.published_at or doc.published_at <= as_of
                ):
                    unique.setdefault((doc.url, doc.content), doc)
        return list(unique.values())

    def runs(self, mode: str | None = None) -> list[CognitiveState]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT payload FROM runs" + (" WHERE mode=?" if mode else ""),
                (mode,) if mode else (),
            ).fetchall()
        return sorted(
            (CognitiveState.model_validate_json(r[0]) for r in rows),
            key=lambda s: s.generated_at,
            reverse=True,
        )
