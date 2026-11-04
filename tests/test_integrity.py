from datetime import datetime, timedelta, timezone

import httpx
import numpy as np
import pytest
from pydantic import ValidationError

from belief.baseline import MissingAnchor, select_anchor
from belief.distribution import interval_probabilities, simulate
from belief.scenario_updater import update_belief
from core.budget import Budget, BudgetExceeded
from core.config import MarketRules, Settings, load_config
from core.controller import run_forecast, validate_question
from core.llm import JsonLLM, ModelError
from core.schemas import CognitiveState, Extraction, Reasoning, ResearchPlan
from evaluation.history import compare_runs
from evaluation.metrics import brier_score
from memory.evidence_store import EvidenceStore
from perception.demo import DemoLLM, DemoSearch
from perception.evidence_extractor import extract, source_quality
from perception.search_client import SearchError, TavilySearch
from reasoning.causal_reasoner import reason
from reasoning.critic import critique

CUTOFF = datetime(2026, 11, 2, tzinfo=timezone.utc)


def evidence_fixture():
    return extract(DemoSearch(CUTOFF).search("test"), DemoLLM(), CUTOFF)


@pytest.mark.parametrize("mutation", ["gap", "overlap", "no_tail", "no_zero", "duplicate_label"])
def test_interval_partition_validation(mutation):
    _, rules = load_config()
    data = rules.model_dump()
    if mutation == "gap":
        data["intervals"][1]["lower"] = 301
    elif mutation == "overlap":
        data["intervals"][1]["lower"] = 299
    elif mutation == "no_tail":
        data["intervals"][-1]["upper"] = 2000
    elif mutation == "no_zero":
        data["intervals"][0]["lower"] = 1
    else:
        data["intervals"][1]["label"] = data["intervals"][0]["label"]
    with pytest.raises(ValidationError):
        MarketRules.model_validate(data)


def test_boundary_exact_membership():
    _, rules = load_config()
    rows = interval_probabilities(np.array([i.lower for i in rules.intervals]), rules.intervals)
    assert all(p.probability == pytest.approx(1 / len(rules.intervals)) for p in rows)


@pytest.mark.parametrize("samples", [[], [np.nan], [-1], [np.inf]])
def test_invalid_samples_refused(samples):
    _, rules = load_config()
    with pytest.raises(ValueError):
        interval_probabilities(np.array(samples), rules.intervals)


def test_future_source_excluded_before_model():
    results = DemoSearch(CUTOFF).search("test")
    results[0].published_at = CUTOFF + timedelta(seconds=1)
    evidence = extract(results, DemoLLM(), CUTOFF)
    assert len(evidence) == 3
    assert not any(e.valuation_usd_billion for e in evidence)


def test_mode_contamination_refused(tmp_path):
    with pytest.raises(ValueError, match="mixed"):
        EvidenceStore(tmp_path / "test.sqlite").save_evidence(evidence_fixture(), "live")


def test_missing_or_wrong_metric_anchor():
    _, rules = load_config()
    evidence = evidence_fixture()
    with pytest.raises(MissingAnchor):
        select_anchor(evidence[1:], rules, CUTOFF, "demo")
    rules.provider = "Forge"
    with pytest.raises(MissingAnchor):
        select_anchor(evidence, rules, CUTOFF, "demo")


def test_no_future_retrieval_anchor():
    _, rules = load_config()
    evidence = evidence_fixture()
    evidence[0].retrieved_at = CUTOFF + timedelta(seconds=1)
    with pytest.raises(MissingAnchor):
        select_anchor(evidence, rules, CUTOFF, "demo")


def test_wrong_anchor_quote_refused():
    class BadQuote(DemoLLM):
        def generate(self, schema, instruction, context):
            result = super().generate(schema, instruction, context)
            if schema is Extraction:
                result.claims[0].valuation_quote = "USD 999 billion"
            return result

    with pytest.raises(ValueError, match="quote not found"):
        extract(DemoSearch(CUTOFF).search("test"), BadQuote(), CUTOFF)


def test_wrong_anchor_unit_refused():
    class WrongUnit(DemoLLM):
        def generate(self, schema, instruction, context):
            result = super().generate(schema, instruction, context)
            result.claims[0].valuation_usd_billion = 500000
            return result

    with pytest.raises(ValueError, match="inconsistent"):
        extract(DemoSearch(CUTOFF).search("test"), WrongUnit(), CUTOFF)


def test_fabricated_evidence_reference_refused():
    class BadReference(DemoLLM):
        def generate(self, schema, instruction, context):
            result = super().generate(schema, instruction, context)
            if schema is Reasoning:
                result.hypotheses[0].evidence_ids = ["invented"]
            return result

    with pytest.raises(ValueError, match="unknown evidence"):
        reason(BadReference(), evidence_fixture(), "OpenAI")


def test_source_domain_spoofing():
    assert source_quality("https://reuters.com.evil.invalid/news")[0] == "unknown"
    assert source_quality("https://www.reuters.com/news")[0] == "reporting"


def test_conflicting_duplicate_anchor_disputed():
    evidence = evidence_fixture()
    copy = evidence[0].model_copy(
        update={"evidence_id": "conflicting", "valuation_usd_billion": 600}
    )
    review = critique(DemoLLM(), evidence + [copy], [])
    assert evidence[0].evidence_id in review.disputed_evidence
    assert "conflicting" in review.disputed_evidence


def test_unpriced_update_and_cap():
    settings, rules = load_config()
    rules.provider = "financing_proxy"
    evidence = evidence_fixture()
    hs = reason(DemoLLM(), evidence, "OpenAI")
    state = CognitiveState(
        question="OpenAI",
        as_of=CUTOFF,
        target_date=rules.target_date,
        mode="demo",
        retrieved_evidence=evidence,
        hypotheses=hs,
        critique=critique(DemoLLM(), evidence, hs),
    )
    posterior = update_belief(state, settings, rules)
    assert posterior["scenario_assumptions"]["net_log_shift"] < 0
    base, extreme = simulate(500, 0.2, settings, shift=100)
    assert np.allclose(extreme / base, np.exp(settings.max_total_log_shift))
    assert posterior == update_belief(state, settings, rules)


def test_ipo_invalidates_settlement():
    settings, rules = load_config()
    evidence = evidence_fixture()
    evidence[1].confidence = 0.9
    evidence[1].epistemic_status = "Verified Fact"
    review = critique(DemoLLM(), evidence, [])
    review.invalid_settlement_evidence = [evidence[1].evidence_id]
    state = CognitiveState(
        question="OpenAI",
        as_of=CUTOFF,
        target_date=rules.target_date,
        mode="demo",
        retrieved_evidence=evidence,
        critique=review,
    )
    with pytest.raises(MissingAnchor, match="IPO"):
        update_belief(state, settings, rules)


def test_schema_validated_llm_response(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")

    def response(*args, **kwargs):
        return httpx.Response(
            200,
            request=httpx.Request("POST", "https://example.invalid"),
            json={
                "choices": [{"message": {"content": '{"items": []}'}}],
                "usage": {"total_tokens": 17},
            },
        )

    monkeypatch.setattr(httpx, "post", response)
    budget = Budget(Settings())
    with pytest.raises(ModelError, match="validation"):
        JsonLLM(budget).generate(ResearchPlan, "test", {})
    assert budget.actual_tokens == 34  # one bounded schema repair, both calls accounted
    assert budget.llm_calls == 2


def test_budget_exhaustion_prevents_network(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")

    def network_forbidden(*args, **kwargs):
        pytest.fail("Network was called after exhausting budget")

    monkeypatch.setattr(httpx, "post", network_forbidden)
    with pytest.raises(BudgetExceeded):
        JsonLLM(Budget(Settings(max_tokens=100))).generate(ResearchPlan, "test", {})


def test_search_success_preserves_sources(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")

    def response(*args, **kwargs):
        return httpx.Response(
            200,
            request=httpx.Request("POST", "https://api.tavily.com/search"),
            json={
                "results": [
                    {
                        "title": "Fixture",
                        "url": "https://source.invalid/a",
                        "content": "Fixture content",
                        "published_date": "2026-10-01T10:00:00Z",
                    }
                ]
            },
        )

    monkeypatch.setattr(httpx, "post", response)
    item = TavilySearch(Budget(Settings())).search("query")[0]
    assert item.url == "https://source.invalid/a"
    assert item.content == "Fixture content" and item.query == "query"
    assert item.published_at.year == 2026 and not item.synthetic


def test_failed_run_is_persisted(tmp_path):
    settings, rules = load_config()
    settings.database = str(tmp_path / "test.sqlite")
    settings.output_dir = str(tmp_path / "reports")

    class Unavailable:
        def search(self, query):
            raise SearchError("Service unavailable")

    with pytest.raises(SearchError):
        run_forecast(
            "OpenAI valuation",
            settings,
            rules,
            demo=True,
            as_of=CUTOFF,
            search_client=Unavailable(),
        )
    saved = EvidenceStore(settings.database).runs()[0]
    assert saved.status == "failed" and saved.forecast is None
    assert saved.trace[-1] == "Failed"
    assert len(saved.search_history) == settings.queries_per_round


@pytest.mark.parametrize(
    "question", ["Other company valuation", "OpenAI 2027-12-31 valuation", "OpenAI ever reach $1T"]
)
def test_invalid_task_refused(question):
    _, rules = load_config()
    with pytest.raises(ValueError):
        validate_question(question, rules)


def test_metrics_are_not_fake_backtest():
    assert brier_score([1, 0], 0) == 0
    assert brier_score([0, 1], 0) == 2
    with pytest.raises(ValueError):
        brier_score([0.7, 0.7], 0)


def test_comparison_rejects_changed_boundaries(tmp_path):
    settings, rules = load_config()
    settings.database = str(tmp_path / "test.sqlite")
    settings.output_dir = str(tmp_path / "reports")
    first = run_forecast("OpenAI valuation", settings, rules, demo=True, as_of=CUTOFF)
    second = first.model_copy(deep=True)
    second.belief_state["rules_snapshot"]["intervals"][0]["upper"] = 301
    with pytest.raises(ValueError, match="boundaries"):
        compare_runs(first, second)
