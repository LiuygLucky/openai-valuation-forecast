"""Deterministic acceptance checks, separate from LLM confidence or prose."""

from urllib.parse import urlsplit

from core.config import Settings
from core.schemas import CognitiveState


class InsufficientEvidence(ValueError):
    pass


def assess_coverage(state: CognitiveState, settings: Settings) -> dict:
    accepted = set(state.critique.accepted_evidence) if state.critique else set()
    evidence = [
        e
        for e in state.retrieved_evidence
        if e.evidence_id in accepted
        and (e.synthetic or (e.confidence >= 0.6 and e.claim_kind in ("fact", "forecast")))
    ]
    categories = sorted({e.category for e in evidence if e.category != "other"})
    # www/non-www are the same publisher; syndication is handled by the critic first.
    sources = sorted(
        {(urlsplit(e.source_url).hostname or "").removeprefix("www.") for e in evidence}
    )
    directions = {e.impact_direction for e in evidence}
    has_positive = bool(directions & {"positive", "mixed"})
    has_negative = bool(directions & {"negative", "mixed"})
    gaps = []
    if len(sources) < settings.min_sources:
        gaps.append("有效独立来源少于两个")
    if len(categories) < settings.min_categories:
        gaps.append("有效重要影响因素类别少于三个")
    if not has_positive:
        gaps.append("缺少有来源的正面因素")
    if not has_negative:
        gaps.append("缺少有来源的负面因素")
    known = {e.evidence_id for e in evidence}
    if not any(known.intersection(h.evidence_ids) for h in state.hypotheses):
        gaps.append("缺少有效证据支持的因果机制假设")
    if not any(
        h.direction in ("positive", "negative", "mixed") and known.intersection(h.evidence_ids)
        for h in state.hypotheses
    ):
        gaps.append("因果假设全部为中性，缺少可解释方向的机制")
    return {
        "passed": not gaps,
        "sources": sources,
        "categories": categories,
        "has_positive": has_positive,
        "has_negative": has_negative,
        "accepted_ids": sorted(known),
        "gaps": gaps,
        "thresholds": {
            "min_sources": settings.min_sources,
            "min_categories": settings.min_categories,
        },
    }


def coverage_queries(coverage: dict, year: int) -> list[str]:
    categories = set(coverage.get("categories", []))
    queries = []
    if "revenue" not in categories or not coverage.get("has_positive"):
        queries.append(f"OpenAI revenue enterprise customers growth {year} site:reuters.com")
    if "profitability" not in categories or not coverage.get("has_negative"):
        queries.append(f"OpenAI cash burn forecast through 2030 {year} site:reuters.com")
    if "competition" not in categories:
        queries.append(f"OpenAI Anthropic Google competition market share {year} site:reuters.com")
    return queries
