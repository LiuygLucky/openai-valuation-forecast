"""Rebuild a small in-memory FAISS index from time-filtered SQLite snapshots."""

import faiss
import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer

from core.config import ROOT
from memory.embeddings import EmbeddingClient


class VectorMemory:
    def __init__(self, model="hashing-char-1024", budget=None, cache_path=None):
        self.model_name = model
        self.encoder = None
        self.api = None
        if model.startswith("api:"):
            if budget is None:
                raise ValueError("API embeddings require an explicit budget")
            self.api = EmbeddingClient(
                model.removeprefix("api:"), budget, cache_path or ROOT / "data/embeddings.sqlite"
            )
        elif model != "hashing-char-1024":
            from sentence_transformers import SentenceTransformer

            self.encoder = SentenceTransformer(model, device="cpu")
        self.hasher = HashingVectorizer(
            n_features=1024, analyzer="char", ngram_range=(2, 4), alternate_sign=False, norm="l2"
        )

    def embed(self, texts):
        if self.api:
            return self.api.embed(texts)
        if self.encoder is not None:
            return np.asarray(
                self.encoder.encode(texts, normalize_embeddings=True), dtype="float32"
            )
        # Offline baseline representation, explicitly NOT semantic neural embeddings.
        return self.hasher.transform(texts).toarray().astype("float32")

    def retrieve(self, question, evidence, k=16):
        if not evidence:
            return []
        vectors = self.embed([f"{e.title} {e.category} {e.claim}" for e in evidence])
        index = faiss.IndexFlatIP(vectors.shape[1])
        index.add(vectors)
        _, ids = index.search(self.embed([question]), min(k, len(evidence)))
        ranked = [evidence[i] for i in ids[0] if i >= 0]
        # Preserve the most recent valuation anchor even under multilingual lexical mismatch.
        anchors = sorted(
            [e for e in evidence if e.valuation_usd_billion],
            key=lambda e: (e.confidence >= 0.75, e.event_at or e.published_at or e.retrieved_at),
            reverse=True,
        )
        if anchors and anchors[0] not in ranked:
            ranked = [anchors[0]] + ranked[: k - 1]
        # Diversify factors without hiding semantic ranking: reserve one representative per category.
        representatives = []
        for e in sorted(evidence, key=lambda x: (-x.confidence, -x.relevance)):
            if e.category not in {r.category for r in representatives}:
                representatives.append(e)
        protected = ([anchors[0]] if anchors else []) + representatives
        combined = {e.evidence_id: e for e in protected + ranked}
        ranked = list(combined.values())[:k]
        return ranked
