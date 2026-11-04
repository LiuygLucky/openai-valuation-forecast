from datetime import datetime, timezone

import pytest

from belief.baseline import MissingAnchor, select_anchor
from core.config import load_config
from core.schemas import CognitiveState, Critique, Extraction, Hypothesis, SearchResult
from perception.demo import DemoLLM
from perception.evidence_extractor import extract, official_forge_anchor
from perception.research_planner import plan_research
from reasoning.coverage import assess_coverage


class EmptyExtractor:
    def generate(self, schema, instruction, context):
        assert schema is Extraction
        return Extraction(claims=[])


def forge_result(url="https://forgeglobal.com/insights/openai-upcoming-ipo-news/"):
    return SearchResult(
        title="OpenAI Upcoming IPO",
        url=url,
        source="Forge",
        published_at=datetime(2026, 9, 24, tzinfo=timezone.utc),
        retrieved_at=datetime(2026, 11, 3, tzinfo=timezone.utc),
        content=(
            "OpenAI's Forge Price is $721.85 at an $894.33 billion valuation "
            "as of September 21, 2026."
        ),
        query="OpenAI Forge Price valuation site:forgeglobal.com",
    )


def test_forge_first_party_observation_is_distinct_from_financing():
    settings, rules = load_config()
    rules.provider = "Forge"
    as_of = datetime(2026, 11, 3, tzinfo=timezone.utc)
    evidence = extract([forge_result()], EmptyExtractor(), as_of)
    assert len(evidence) == 1
    mark = evidence[0]
    assert mark.valuation_usd_billion == 894.33
    assert mark.valuation_metric == "Forge"
    assert mark.valuation_status == "observed"
    assert mark.event_at.date().isoformat() == "2026-09-21"
    assert select_anchor(evidence, rules, as_of, "live").evidence_id == mark.evidence_id

    rules.provider = "financing_proxy"
    with pytest.raises(MissingAnchor):
        select_anchor(evidence, rules, as_of, "live")
    rules.provider = "Forge"
    with pytest.raises(MissingAnchor):
        select_anchor(evidence, rules, datetime(2026, 12, 1, tzinfo=timezone.utc), "live")


def test_forge_host_and_missing_mark_cannot_be_anchor():
    assert official_forge_anchor(forge_result("https://forgeglobal.com.evil.invalid/x")) is None
    result = forge_result()
    result.content = "OpenAI last funding round post-money valuation was $852 billion."
    assert official_forge_anchor(result) is None


def test_forge_research_starts_with_provider_query():
    _, rules = load_config()
    rules.provider = "Forge"
    plan = plan_research(
        DemoLLM(), "OpenAI 2026 年底 Forge 估值", rules, datetime(2026, 11, 3, tzinfo=timezone.utc)
    )
    assert "site:forgeglobal.com" in plan[0].suggested_queries[0]


def test_all_neutral_mechanisms_fail_coverage():
    settings, rules = load_config()
    as_of = datetime(2026, 11, 3, tzinfo=timezone.utc)
    evidence = extract([forge_result()], EmptyExtractor(), as_of)
    neutral = Hypothesis(
        event="Forge observation",
        mechanism=["Price observed", "No directional change inferred"],
        direction="neutral",
        counterarguments=["New information may move the price"],
        evidence_ids=[evidence[0].evidence_id],
        uncertainties=["Uncalibrated"],
        priced_in="likely",
    )
    state = CognitiveState(
        question="OpenAI Forge valuation",
        as_of=as_of,
        target_date=rules.target_date,
        retrieved_evidence=evidence,
        hypotheses=[neutral],
        critique=Critique(
            accepted_evidence=[evidence[0].evidence_id],
            disputed_evidence=[],
            missing_information=[],
            potential_biases=[],
            recommended_followup_queries=[],
        ),
    )
    assert "因果假设全部为中性，缺少可解释方向的机制" in assess_coverage(state, settings)["gaps"]
