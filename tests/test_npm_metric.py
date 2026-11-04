import json
from datetime import datetime, timezone

import pytest

from belief.baseline import MissingAnchor, select_anchor
from belief.scenario_updater import update_belief
from core.config import load_config
from core.schemas import CognitiveState, Critique, Extraction, Hypothesis, SearchResult
from perception.demo import DemoLLM
from perception.evidence_extractor import extract, official_npm_share_price
from perception.npm_official import NPM_API_URL, NPM_PAGE_URL, parse_npm_snapshot
from perception.research_planner import plan_research
from reasoning.critic import critique, event_groups


class EmptyExtractor:
    def generate(self, schema, instruction, context):
        assert schema is Extraction
        return Extraction(claims=[])


def npm_result(url="https://www.nasdaqprivatemarket.com/company/open-ai/"):
    return SearchResult(
        title="OpenAI Stock",
        url=url,
        source="Nasdaq Private Market",
        published_at=datetime(2026, 10, 21, tzinfo=timezone.utc),
        retrieved_at=datetime(2026, 11, 4, tzinfo=timezone.utc),
        content=(
            "Nasdaq Private Market estimates that OpenAI price per share was "
            "$1006.33 as of October 20, 2026. This is the NPM price."
        ),
        query="OpenAI NPM Price site:nasdaqprivatemarket.com",
    )


def test_npm_price_is_recorded_as_share_price_and_never_as_company_value():
    _, rules = load_config()
    as_of = datetime(2026, 11, 4, tzinfo=timezone.utc)
    evidence = extract([npm_result()], EmptyExtractor(), as_of)
    assert len(evidence) == 1
    mark = evidence[0]
    assert mark.share_price_usd == 1006.33
    assert mark.valuation_usd_billion is None
    assert mark.valuation_metric == "NPM_price_per_share"
    assert mark.event_at.date().isoformat() == "2026-10-20"
    with pytest.raises(MissingAnchor):
        select_anchor(evidence, rules, as_of, "live")


def test_npm_source_must_be_official_and_dated():
    assert (
        official_npm_share_price(npm_result("https://nasdaqprivatemarket.com.evil.invalid/"))
        is None
    )
    result = npm_result()
    result.content = "OpenAI NPM Price $1006.33."
    assert official_npm_share_price(result) is None


def test_npm_research_starts_with_provider_query():
    _, rules = load_config()
    plan = plan_research(
        DemoLLM(), "OpenAI 2026 年底 NPM 估值", rules, datetime(2026, 11, 4, tzinfo=timezone.utc)
    )
    assert "site:nasdaqprivatemarket.com" in plan[0].suggested_queries[0]


def official_snapshot(mark_date="2026-10-29", company="OpenAI", valuation=1254731740680.9697):
    as_of = datetime(2026, 11, 4, tzinfo=timezone.utc)
    return SearchResult(
        title="OpenAI NPM public company pricing snapshot",
        url=NPM_API_URL,
        source=NPM_PAGE_URL,
        published_at=as_of,
        retrieved_at=as_of,
        content=json.dumps(
            {
                "company": {"dba_name": company},
                "latest_npm_price": {
                    "price": 1015.13244833,
                    "date": mark_date,
                    "implied_valuation": valuation,
                },
            },
            separators=(",", ":"),
        ),
        query="Official NPM OpenAI valuation feed",
    )


def test_npm_official_implied_valuation_is_valid_anchor_with_raw_snapshot():
    _, rules = load_config()
    result = official_snapshot()
    mark = parse_npm_snapshot(result)
    assert mark.valuation_usd_billion == pytest.approx(1254.7317406809697)
    assert mark.share_price_usd == pytest.approx(1015.13244833)
    assert mark.support_quote in mark.raw_content
    assert mark.event_at.date().isoformat() == "2026-10-29"
    assert select_anchor([mark], rules, result.retrieved_at, "live") == mark
    with pytest.raises(MissingAnchor):
        select_anchor([mark], rules, datetime(2026, 11, 14, tzinfo=timezone.utc), "live")


def test_npm_official_feed_rejects_wrong_company_and_missing_valuation():
    with pytest.raises(ValueError, match="not OpenAI"):
        parse_npm_snapshot(official_snapshot(company="Anthropic"))
    with pytest.raises((ValueError, TypeError)):
        parse_npm_snapshot(official_snapshot(valuation=None))


def test_npm_dated_observations_are_not_conflicting_duplicates():
    old = parse_npm_snapshot(official_snapshot())
    new = parse_npm_snapshot(official_snapshot("2026-11-02", valuation=1263746113857.92))
    assert len(event_groups([old, new])) == 2

    class DisputingCritic:
        def generate(self, schema, instruction, context):
            return Critique(
                accepted_evidence=[],
                disputed_evidence=[old.evidence_id, new.evidence_id],
                missing_information=[],
                potential_biases=[],
                recommended_followup_queries=[],
            )

    review = critique(DisputingCritic(), [old, new], [])
    assert new.evidence_id in review.accepted_evidence
    assert old.evidence_id in review.disputed_evidence
    _, rules = load_config()
    assert select_anchor(
        [e for e in (old, new) if e.evidence_id in review.accepted_evidence],
        rules,
        new.retrieved_at,
        "live",
    ) == new


def test_sourced_forward_risk_changes_distribution_without_repricing_old_fact():
    settings, rules = load_config()
    anchor = parse_npm_snapshot(official_snapshot())
    forecast = anchor.model_copy(
        update={
            "evidence_id": "future-cash-burn",
            "event_key": "cash-burn-2026-2030",
            "category": "profitability",
            "claim_kind": "forecast",
            "valuation_status": "unknown",
            "valuation_usd_billion": None,
            "share_price_usd": None,
            "valuation_metric": None,
            "event_at": None,
            "published_at": datetime(2026, 10, 1, tzinfo=timezone.utc),
            "support_quote": "Forecast cash burn between 2026 and 2030",
            "claim": "Forecast cash burn between 2026 and 2030",
            "impact_direction": "negative",
        }
    )
    state = CognitiveState(
        question="OpenAI 2026 valuation",
        as_of=datetime(2026, 11, 4, tzinfo=timezone.utc),
        target_date=rules.target_date,
        retrieved_evidence=[anchor, forecast],
        critique=Critique(
            accepted_evidence=[anchor.evidence_id, forecast.evidence_id],
            disputed_evidence=[],
            missing_information=[],
            potential_biases=[],
            recommended_followup_queries=[],
        ),
        hypotheses=[
            Hypothesis(
                event="Future cash burn",
                mechanism=["cash burn", "valuation risk"],
                direction="negative",
                counterarguments=["May be lower than expected"],
                evidence_ids=[forecast.evidence_id],
                uncertainties=["Future realization"],
                priced_in="likely",
            )
        ],
    )
    updated = update_belief(state, settings, rules)
    assert updated["future_realization_risks"][0]["event_key"] == forecast.event_key
    assert updated["scenario_assumptions"]["net_log_shift"] == 0
    assert updated["posterior_distribution"] != updated["baseline_distribution"]
    state.critique.accepted_evidence = [anchor.evidence_id]
    baseline_only = update_belief(state, settings, rules)
    assert not baseline_only["future_realization_risks"]
    assert baseline_only["posterior_distribution"] == baseline_only["baseline_distribution"]


def test_new_post_anchor_fact_with_mechanism_has_directional_update():
    settings, rules = load_config()
    anchor = parse_npm_snapshot(official_snapshot())
    later = anchor.model_copy(
        update={
            "evidence_id": "new-revenue-fact",
            "event_key": "new-revenue-after-anchor",
            "category": "revenue",
            "claim_kind": "fact",
            "valuation_status": "unknown",
            "valuation_usd_billion": None,
            "share_price_usd": None,
            "valuation_metric": None,
            "event_at": None,
            "published_at": datetime(2026, 11, 5, tzinfo=timezone.utc),
            "retrieved_at": datetime(2026, 11, 5, tzinfo=timezone.utc),
            "impact_direction": "positive",
        }
    )
    state = CognitiveState(
        question="OpenAI 2026 valuation",
        as_of=datetime(2026, 11, 5, tzinfo=timezone.utc),
        target_date=rules.target_date,
        retrieved_evidence=[anchor, later],
        critique=Critique(
            accepted_evidence=[anchor.evidence_id, later.evidence_id],
            disputed_evidence=[],
            missing_information=[],
            potential_biases=[],
            recommended_followup_queries=[],
        ),
        hypotheses=[
            Hypothesis(
                event="New revenue fact",
                mechanism=["revenue", "valuation"],
                direction="positive",
                counterarguments=["Effect may be smaller"],
                evidence_ids=[later.evidence_id],
                uncertainties=["Market response"],
                priced_in="unlikely",
            )
        ],
    )
    result = update_belief(state, settings, rules)
    assert next(a for a in result["event_adjustments"] if a["event_key"] == later.event_key)[
        "log_shift"
    ] > 0
    assert result["posterior_distribution"] != result["baseline_distribution"]
