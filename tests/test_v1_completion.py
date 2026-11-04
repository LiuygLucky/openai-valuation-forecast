from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from belief.baseline import MissingAnchor, select_anchor
from belief.scenario_updater import update_belief
from core.budget import Budget
from core.config import load_config
from core.schemas import CognitiveState, ExtractedClaim, Extraction, SearchResult
from core.task_parser import parse_task
from memory.embeddings import EmbeddingClient
from perception.demo import DemoLLM, DemoSearch
from perception.evidence_extractor import extract, official_closed_anchor, validate_valuation
from reasoning.causal_reasoner import reason
from reasoning.coverage import assess_coverage
from reasoning.critic import critique

CUTOFF = datetime(2026, 11, 3, tzinfo=timezone.utc)


def test_literal_official_anchor_never_uses_amount_raised():
    doc = SearchResult(
        title="OpenAI fixture",
        url="https://openai.com/fixture",
        source="fixture",
        published_at=CUTOFF,
        retrieved_at=CUTOFF,
        query="test",
        content="Today, we closed our latest funding round with $120 billion in committed capital at a post money valuation of $800 billion.",
    )
    claim = official_closed_anchor(doc)
    assert claim.valuation_usd_billion == 800
    assert claim.valuation_quote in doc.content
    assert (
        official_closed_anchor(
            doc.model_copy(update={"content": doc.content.replace("we closed", "we plan to close")})
        )
        is None
    )
    assert (
        official_closed_anchor(doc.model_copy(update={"url": "https://openai.com.evil.invalid/"}))
        is None
    )


def test_whole_company_value_not_stake_or_money_raised():
    doc = SearchResult(
        title="OpenAI fixture",
        url="https://openai.com/fixture",
        source="fixture",
        query="fixture",
        content="OpenAI. Today, we closed our latest funding round with $120 billion in committed capital at a post money valuation of $800 billion.",
    )
    claim = official_closed_anchor(doc)
    claim.valuation_usd_billion = 120
    with pytest.raises(ValueError, match="not money raised"):
        validate_valuation(claim, doc)
    claim.valuation_usd_billion = 135
    claim.support_quote = (
        "Microsoft holds an investment in OpenAI valued at approximately $135 billion."
    )
    claim.valuation_quote = "valued at approximately $135 billion"
    doc.content = claim.support_quote
    with pytest.raises(ValueError, match="shareholder stake"):
        validate_valuation(claim, doc)


def test_category_aliases_are_explicit_not_arbitrary():
    data = dict(
        result_index=0,
        claim="fixture",
        category="compute costs",
        impact_direction="negative",
        epistemic_status="Reported Claim",
        event_key="fixture",
        reasoning="fixture",
        relevance=1,
    )
    assert ExtractedClaim.model_validate(data).category == "profitability"
    data["category"] = "arbitrary made up category"
    with pytest.raises(ValueError):
        ExtractedClaim.model_validate(data)


def test_relevant_cost_report_precedes_unrelated_official_page():
    from perception.research_planner import document_priority

    relevant = SearchResult(
        title="OpenAI forecasts cash burn",
        url="https://www.reuters.com/fixture",
        source="Reuters",
        content="OpenAI cash costs",
        query="OpenAI cash burn",
    )
    unrelated = relevant.model_copy(
        update={
            "title": "OpenAI appoints new executive",
            "url": "https://openai.com/fixture",
            "content": "OpenAI expands its business leadership.",
        }
    )
    assert document_priority(relevant, "profitability") < document_priority(
        unrelated, "profitability"
    )


def test_source_filter_passed_to_search(monkeypatch):
    import httpx

    from perception.search_client import TavilySearch

    monkeypatch.setenv("TAVILY_API_KEY", "test-placeholder")

    def post(url, **kwargs):
        assert kwargs["json"]["include_domains"] == ["reuters.com"]
        return httpx.Response(200, request=httpx.Request("POST", url), json={"results": []})

    monkeypatch.setattr("perception.search_client.httpx.post", post)
    settings, _ = load_config()
    assert TavilySearch(Budget(settings)).search("OpenAI site:reuters.com") == []


def test_publication_date_requires_matching_article_and_source_day():
    from perception.search_client import publication_time

    result = {
        "url": "https://www.reuters.com/technology/fixture-2026-09-18",
        "content": "Sep 18, 2026 — OpenAI cash burn forecast.",
    }
    when, basis = publication_time(result)
    assert when == datetime(2026, 9, 18, 23, 59, 59, tzinfo=timezone.utc)
    assert "conservative" in basis
    result["content"] = "Sep 19, 2026 — Different date."
    assert publication_time(result)[0] is None


def test_general_search_metadata_lookup_is_budgeted_and_traced(monkeypatch):
    import httpx

    from perception.search_client import TavilySearch

    monkeypatch.setenv("TAVILY_API_KEY", "test-placeholder")
    calls = []
    url = "https://www.reuters.com/technology/openai-fixture-2026-09-18"

    def post(endpoint, **kwargs):
        topic = kwargs["json"]["topic"]
        calls.append(topic)
        result = {
            "title": "OpenAI cash burn forecast",
            "url": url,
            "content": "OpenAI reported future cash costs.",
        }
        if topic == "news":
            result.update(url=url + "/", published_date="2026-09-18T22:42:32Z")
        return httpx.Response(
            200, request=httpx.Request("POST", endpoint), json={"results": [result]}
        )

    monkeypatch.setattr("perception.search_client.httpx.post", post)
    settings, _ = load_config()
    budget = Budget(settings)
    client = TavilySearch(budget)
    result = client.search("OpenAI cash burn site:reuters.com")
    assert calls == ["general", "news"] and budget.search_calls == 2
    assert len(client.request_history) == 2
    assert result[0].published_time_basis == "search_provider"
    assert result[0].published_at.hour == 22


def test_checkpoint_retries_windows_lock(tmp_path, monkeypatch):
    from pathlib import Path

    from core.checkpoint import write_checkpoint

    replace = Path.replace
    calls = []

    def locked_once(self, target):
        calls.append(1)
        if len(calls) == 1:
            raise PermissionError("temporary reader lock")
        return replace(self, target)

    monkeypatch.setattr(Path, "replace", locked_once)
    monkeypatch.setattr("core.checkpoint.time.sleep", lambda _: None)
    path = tmp_path / "state.json"
    write_checkpoint(path, "{}")
    assert path.read_text() == "{}" and len(calls) == 2


def test_resume_keeps_completed_research_and_budget(tmp_path):
    from core.controller import run_forecast
    from core.schemas import Reasoning
    from memory.evidence_store import EvidenceStore

    class Interrupted(DemoLLM):
        def generate(self, schema, *args):
            if schema is Reasoning:
                raise RuntimeError("simulated interruption")
            return super().generate(schema, *args)

    settings, rules = load_config()
    settings.database = str(tmp_path / "resume.sqlite")
    settings.output_dir = str(tmp_path / "reports")
    with pytest.raises(RuntimeError, match="simulated"):
        run_forecast(
            "OpenAI valuation",
            settings,
            rules,
            demo=True,
            as_of=CUTOFF,
            llm_client=Interrupted(rules.provider),
        )
    previous = EvidenceStore(settings.database).runs("demo")[0]
    result = run_forecast("OpenAI valuation", settings, rules, demo=True, resume_id=previous.run_id)
    assert result.run_id == previous.run_id and result.status == "completed"
    assert result.trace.count("PlanResearch") == 1
    assert "Resumed" in result.trace
    assert result.search_history[: len(previous.search_history)] == previous.search_history


def state_fixture():
    settings, rules = load_config()
    rules.provider = "financing_proxy"
    evidence = extract(DemoSearch(CUTOFF).search("test"), DemoLLM(), CUTOFF)
    hypotheses = reason(DemoLLM(), evidence, "OpenAI valuation")
    state = CognitiveState(
        question="OpenAI valuation",
        as_of=CUTOFF,
        target_date=rules.target_date,
        mode="demo",
        retrieved_evidence=evidence,
        hypotheses=hypotheses,
        critique=critique(DemoLLM(), evidence, hypotheses),
    )
    return settings, rules, state


def test_old_anchor_propagates_from_event_and_is_reproducible():
    settings, rules, state = state_fixture()
    anchor = next(e for e in state.retrieved_evidence if e.valuation_usd_billion)
    origin = CUTOFF - timedelta(days=300)
    anchor.event_at = anchor.published_at = origin
    anchor.stale = True
    old = update_belief(state, settings, rules)
    assert old == update_belief(state, settings, rules)
    assert old["prior_assumptions"]["years"] == pytest.approx(
        (rules.target_date - origin).total_seconds() / (365.25 * 86400)
    )
    anchor.event_at = anchor.published_at = CUTOFF - timedelta(days=1)
    new = update_belief(state, settings, rules)
    assert (
        old["interval_90"][1] - old["interval_90"][0]
        > new["interval_90"][1] - new["interval_90"][0]
    )


def test_live_anchor_rejects_proposals_and_preserves_old_fact():
    settings, rules, state = state_fixture()
    anchor = state.retrieved_evidence[0].model_copy(
        update={
            "synthetic": False,
            "source_type": "official",
            "epistemic_status": "Verified Fact",
            "confidence": 0.9,
            "claim_kind": "fact",
            "valuation_status": "completed",
            "stale": True,
            "published_at": CUTOFF - timedelta(days=300),
            "event_at": None,
        }
    )
    assert select_anchor([anchor], rules, CUTOFF, "live") == anchor
    anchor.valuation_status = "proposed"
    with pytest.raises(MissingAnchor):
        select_anchor([anchor], rules, CUTOFF, "live")


def test_ipo_plan_cannot_invalidate_private_metric():
    from belief.settlement import confirms_invalid_private_metric

    _, _, state = state_fixture()
    evidence = state.retrieved_evidence[0].model_copy(
        update={
            "synthetic": False,
            "claim_kind": "forecast",
            "valuation_status": "proposed",
            "support_quote": "OpenAI is aiming to go public as early as September and preparing a draft prospectus.",
        }
    )
    assert not confirms_invalid_private_metric(evidence)
    evidence.claim_kind = "fact"
    evidence.valuation_status = "unknown"
    evidence.support_quote = "OpenAI filed a draft IPO prospectus."
    assert not confirms_invalid_private_metric(evidence)
    evidence.support_quote = "OpenAI has completed its IPO."
    assert confirms_invalid_private_metric(evidence)
    evidence.support_quote = "Anthropic completed its IPO ahead of OpenAI."
    assert not confirms_invalid_private_metric(evidence)


@pytest.mark.parametrize(
    "date_text,expected", [("2026-03-31", "source_date"), ("2026-03-30", "unknown")]
)
def test_event_date_requires_exact_source_date(date_text, expected):
    result = SearchResult(
        title="fixture",
        url="https://openai.com/fixture",
        source="fixture",
        published_at=CUTOFF - timedelta(days=1),
        retrieved_at=CUTOFF,
        content="OpenAI completed a transaction on March 31, 2026.",
        query="test",
    )
    claim = ExtractedClaim(
        result_index=0,
        claim="Completed transaction",
        category="financing",
        support_quote=result.content,
        claim_kind="fact",
        event_date=date_text,
        event_date_quote="March 31, 2026",
        impact_direction="positive",
        epistemic_status="Verified Fact",
        event_key="fixture",
        reasoning="fixture",
        relevance=1,
    )

    class Client:
        def generate(self, *args):
            return Extraction(claims=[claim])

    evidence = extract([result], Client(), CUTOFF)
    assert evidence[0].event_time_basis == expected
    if expected == "unknown":
        assert evidence[0].event_at is None


def test_future_fact_is_rejected_entirely():
    result = SearchResult(
        title="fixture",
        url="https://openai.com/fixture",
        source="fixture",
        published_at=CUTOFF,
        retrieved_at=CUTOFF,
        content="OpenAI transaction on December 31, 2026.",
        query="test",
    )
    claim = ExtractedClaim(
        result_index=0,
        claim="Completed transaction",
        category="financing",
        support_quote=result.content,
        claim_kind="fact",
        event_date="2026-12-31",
        event_date_quote="December 31, 2026",
        impact_direction="positive",
        epistemic_status="Verified Fact",
        event_key="fixture",
        reasoning="fixture",
        relevance=1,
    )

    class Client:
        def generate(self, *args):
            return Extraction(claims=[claim])

    assert not extract([result], Client(), CUTOFF, strict=False)


def test_coverage_cannot_pass_with_one_sided_single_source():
    settings, _, state = state_fixture()
    assert assess_coverage(state, settings)["passed"]
    for e in state.retrieved_evidence:
        e.source_url = "https://same.invalid/news"
        e.impact_direction = "positive"
        e.category = "revenue"
    result = assess_coverage(state, settings)
    assert not result["passed"] and len(result["gaps"]) == 3


def test_syndicated_forecast_key_alias_is_one_numeric_event():
    from reasoning.critic import event_groups

    _, _, state = state_fixture()
    first = state.retrieved_evidence[0].model_copy(
        update={
            "event_key": "openai_cash_burn_forecast_2026_2030",
            "claim_kind": "forecast",
            "category": "profitability",
            "raw_content": "Original publisher text",
        }
    )
    second = first.model_copy(
        update={
            "evidence_id": "copy",
            "event_key": "openai-cash-burn-2026-2030",
            "raw_content": "Different syndicated article wording",
        }
    )
    assert len(event_groups([first, second])) == 1
    second.claim_kind = "fact"
    assert len(event_groups([first, second])) == 2


def test_raw_snapshot_reuse_preserves_cutoff_and_mode(tmp_path):
    from memory.evidence_store import EvidenceStore

    _, _, state = state_fixture()
    state.search_results = DemoSearch(CUTOFF).search("fixture")
    state.trace = ["Search"]
    store = EvidenceStore(tmp_path / "snapshots.sqlite")
    store.snapshot(state, "Search")
    docs = store.recent_documents(CUTOFF, "demo")
    assert len(docs) == 4
    assert docs[0].retrieved_at == state.search_results[0].retrieved_at
    assert not store.recent_documents(CUTOFF - timedelta(days=1), "demo")
    assert not store.recent_documents(CUTOFF, "live")


def test_task_parses_date_and_explicit_units():
    _, rules = load_config()
    parsed, task = parse_task("OpenAI 2027年底估值，区间边界（万亿美元）：0.5,1,1.5", rules, CUTOFF)
    assert parsed.target_date.year == 2027
    assert [x.lower for x in parsed.intervals] == [0, 500, 1000, 1500]
    assert task["field_origins"]["target_date"] == "question"
    assert parsed.target_date.utcoffset() == timedelta(hours=-5)


@pytest.mark.parametrize(
    ("question", "year"),
    [
        ("预测 OpenAI 今年底估值", 2026),
        ("预测 OpenAI 今年12月底估值", 2026),
        ("预测 OpenAI 明年年终估值", 2027),
        ("预测 OpenAI 后年年底估值", 2028),
        ("预测 OpenAI 2027年12月底估值", 2027),
    ],
)
def test_task_resolves_supported_year_end_phrasings(question, year):
    _, rules = load_config()
    parsed, task = parse_task(question, rules, CUTOFF)
    assert parsed.target_date.year == year
    assert parsed.target_date.month == 12 and parsed.target_date.day == 31
    assert task["field_origins"]["target_date"] == "question"


@pytest.mark.parametrize(
    "question",
    [
        "OpenAI 2026-12-31 2027-12-31 valuation",
        "OpenAI Forge NPM valuation",
        "OpenAI 估值区间边界：500,750",
        "OpenAI 最高估值",
        "OpenAI 2027年估值",
        "OpenAI 明年第三季度估值",
        "OpenAI 年底估值",
        "OpenAI 2026年底及2027年估值",
        "OpenAI 2027年Q4估值",
        "OpenAI 春节前估值",
        "OpenAI 三个月后估值",
        "OpenAI 12/31 估值",
    ],
)
def test_ambiguous_tasks_rejected(question):
    _, rules = load_config()
    with pytest.raises(ValueError):
        parse_task(question, rules, CUTOFF)


def test_embedding_batch_cache_and_response_indices(tmp_path, monkeypatch):
    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://test.invalid/v1")
    monkeypatch.setenv("EMBEDDING_API_KEY", "test-placeholder")
    calls = []

    class Response:
        def __init__(self, count):
            self.count = count

        def raise_for_status(self):
            pass

        def json(self):
            return {
                "data": [
                    {"index": i, "embedding": [i + 1.0] * 1024} for i in reversed(range(self.count))
                ],
                "usage": {"total_tokens": self.count},
            }

    def post(url, **kwargs):
        calls.append(len(kwargs["json"]["input"]))
        return Response(calls[-1])

    monkeypatch.setattr("memory.embeddings.httpx.post", post)
    settings, _ = load_config()
    client = EmbeddingClient("fixture", Budget(settings), tmp_path / "vectors.sqlite")
    texts = [str(i) for i in range(12)]
    first = client.embed(texts)
    assert calls == [10, 2]
    assert np.array_equal(first, client.embed(texts))
    assert calls == [10, 2]
    assert np.allclose(np.linalg.norm(first, axis=1), 1)
