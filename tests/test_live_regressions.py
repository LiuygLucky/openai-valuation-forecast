from datetime import datetime, timezone

from core.schemas import ResearchItem
from memory.evidence_store import EvidenceStore
from perception.demo import DemoLLM, DemoSearch
from perception.evidence_extractor import extract
from perception.research_planner import diverse_queries


def test_queries_cover_topics_before_repeating_one_topic():
    items = [
        ResearchItem(
            research_question=topic,
            rationale="test",
            priority=i + 1,
            suggested_queries=[topic + " first", topic + " second"],
            expected_information="facts",
        )
        for i, topic in enumerate(["valuation", "revenue", "risk"])
    ]
    assert diverse_queries(items)[:3] == ["valuation first", "revenue first", "risk first"]


def test_multiple_claims_in_one_document_are_not_lost(tmp_path):
    class MultipleClaims(DemoLLM):
        def generate(self, schema, instruction, context):
            result = super().generate(schema, instruction, context)
            extra = result.claims[0].model_copy(
                update={
                    "claim": "SYNTHETIC distinct revenue claim",
                    "category": "revenue",
                    "event_key": "different-event",
                    "valuation_usd_billion": None,
                    "valuation_quote": None,
                    "valuation_metric": None,
                }
            )
            result.claims.append(extra)
            return result

    cutoff = datetime(2026, 11, 2, tzinfo=timezone.utc)
    evidence = extract(DemoSearch(cutoff).search("test"), MultipleClaims(), cutoff)
    store = EvidenceStore(tmp_path / "memory.sqlite")
    store.save_evidence(evidence, "demo")
    assert len(store.query(cutoff, "demo")) == 5
    assert evidence[0].document_id == evidence[-1].document_id
    assert evidence[0].evidence_id != evidence[-1].evidence_id


def test_bad_anchor_is_quarantined_without_losing_other_evidence():
    class BadQuote(DemoLLM):
        def generate(self, schema, instruction, context):
            result = super().generate(schema, instruction, context)
            result.claims[0].valuation_quote = "USD 999 billion"
            return result

    cutoff = datetime(2026, 11, 2, tzinfo=timezone.utc)
    warnings = []
    evidence = extract(
        DemoSearch(cutoff).search("test"), BadQuote(), cutoff, strict=False, warnings=warnings
    )
    assert len(evidence) == 3
    assert not any(e.valuation_usd_billion for e in evidence)
    assert len(warnings) == 1 and "quote not found" in warnings[0]


def test_extraction_version_does_not_overwrite_immutable_old_claim(tmp_path, monkeypatch):
    import perception.evidence_extractor as module

    cutoff = datetime(2026, 11, 2, tzinfo=timezone.utc)
    docs = DemoSearch(cutoff).search("test")
    old = extract(docs, DemoLLM(), cutoff)
    monkeypatch.setattr(module, "EXTRACTION_VERSION", "test-next")
    new = extract(docs, DemoLLM(), cutoff)
    assert old[0].evidence_id != new[0].evidence_id
    store = EvidenceStore(tmp_path / "memory.sqlite")
    store.save_evidence(old + new, "demo")
    assert len(store.query(cutoff, "demo")) == 8
