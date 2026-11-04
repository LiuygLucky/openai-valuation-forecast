from datetime import datetime
from urllib.parse import urlsplit

from core.config import MarketRules
from core.schemas import Evidence
from perception.npm_official import NPM_API_URL, NPM_PAGE_URL


class MissingAnchor(ValueError):
    pass


def select_anchor(
    evidence: list[Evidence],
    rules: MarketRules,
    as_of: datetime,
    mode: str,
    max_age_days: int = 1095,
) -> Evidence:
    candidates = [
        e
        for e in evidence
        if e.valuation_usd_billion is not None
        and e.synthetic == (mode == "demo")
        and e.published_at is not None
        and e.published_at <= as_of
        and e.retrieved_at <= as_of
        and (e.event_at is None or e.event_at <= as_of)
        and (as_of - (e.event_at or e.published_at)).days
        <= (
            min(max_age_days, 14)
            if rules.provider == "NPM"
            else min(max_age_days, 60)
            if rules.provider == "Forge"
            else max_age_days
        )
        and e.valuation_metric == rules.provider
        and (
            mode == "demo"
            or (
                rules.provider == "Forge"
                and (urlsplit(e.source_url).hostname or "").removeprefix("www.")
                == "forgeglobal.com"
                and e.confidence >= 0.75
                and e.claim_kind == "fact"
                and e.valuation_status == "observed"
                and e.event_at is not None
                and e.event_at.date() <= e.published_at.date()
            )
            or (
                rules.provider == "NPM"
                and e.source_url == NPM_PAGE_URL
                and e.source == NPM_API_URL
                and e.confidence >= 0.75
                and e.claim_kind == "fact"
                and e.valuation_status == "observed"
                and e.event_at is not None
                and e.event_at.date() <= e.published_at.date()
            )
            or (
                rules.provider not in ("Forge", "NPM")
                and e.confidence >= 0.75
                and e.epistemic_status in ("Verified Fact", "Reported Claim")
                and e.claim_kind == "fact"
                and e.valuation_status == "completed"
                and (e.event_at is not None or e.source_type == "official")
            )
        )
    ]
    if not candidates:
        raise MissingAnchor(
            "No reliable, dated, sourced anchor for configured metric; refusing probabilities"
        )
    return max(candidates, key=lambda e: (e.event_at or e.published_at, e.confidence))
