from datetime import datetime, timedelta, timezone

from core.config import load_config
from memory.evidence_store import EvidenceStore
from memory.vector_store import VectorMemory
from perception.demo import DemoLLM, DemoSearch
from perception.evidence_extractor import extract
from reasoning.causal_reasoner import reason
from reasoning.critic import critique


def fixtures():
    as_of = datetime(2026, 11, 2, tzinfo=timezone.utc)
    return as_of, extract(DemoSearch(as_of).search("test"), DemoLLM(), as_of)


def test_sources_round_trip_and_time_filter(tmp_path):
    as_of, evidence = fixtures()
    store = EvidenceStore(tmp_path / "memory.sqlite")
    store.save_evidence(evidence, "demo")
    store.save_evidence(evidence, "demo")
    assert len(store.query(as_of, "demo")) == 4
    assert store.get(evidence[0].evidence_id, "demo") == evidence[0]
    assert not store.query(as_of - timedelta(days=1), "demo")  # not yet observed
    future = evidence[0].model_copy(
        update={"evidence_id": "future", "published_at": as_of + timedelta(days=1)}
    )
    store.save_evidence([future], "demo")
    assert len(store.query(as_of, "demo")) == 4
    assert not store.query(as_of, "live")


def test_duplicate_event_not_counted_twice():
    _, evidence = fixtures()
    duplicate = evidence[0].model_copy(
        update={"evidence_id": "copy", "source_url": "https://copy.invalid/"}
    )
    result = critique(DemoLLM(), evidence + [duplicate], [])
    assert len(result.accepted_evidence) == 4
    assert len(result.disputed_evidence) == 1


def test_causal_hypotheses_and_rag():
    _, evidence = fixtures()
    settings, _ = load_config()
    retrieved = VectorMemory("hashing-char-1024").retrieve("OpenAI costs", evidence, 3)
    assert len(retrieved) == 3
    assert any(e.valuation_usd_billion for e in retrieved)
    hypotheses = reason(DemoLLM(), retrieved, "OpenAI valuation")
    assert all(h.counterarguments and h.evidence_ids and len(h.mechanism) >= 2 for h in hypotheses)
