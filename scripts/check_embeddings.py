"""One small real semantic-embedding probe; prints no credentials or vector contents."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.budget import Budget
from core.config import ROOT, load_config
from core.schemas import utcnow
from memory.vector_store import VectorMemory

settings, _ = load_config()
budget = Budget(settings)
encoder = VectorMemory(settings.embedding_model, budget, ROOT / settings.embedding_cache)
vectors = encoder.embed(
    [
        "OpenAI revenue grows through enterprise subscriptions.",
        "OpenAI 通过企业订阅实现收入增长。",
        "Ocean tides are driven by lunar gravity.",
    ]
)
result = {
    "checked_at": utcnow().isoformat(),
    "model": settings.embedding_model,
    "shape": list(vectors.shape),
    "cross_language_similarity": float(vectors[0] @ vectors[1]),
    "unrelated_similarity": float(vectors[0] @ vectors[2]),
    "usage": budget.snapshot(),
}
result["passed"] = result["cross_language_similarity"] > result["unrelated_similarity"]
(ROOT / "reports/embedding_validation.json").write_text(
    json.dumps(result, indent=2), encoding="utf-8"
)
print(json.dumps(result, indent=2))
if not result["passed"]:
    raise SystemExit("Semantic embedding smoke test failed")
