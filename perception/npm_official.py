"""Read NPM's public OpenAI valuation feed used by its company data page."""

import json
import re
from datetime import date, datetime, time
from math import isfinite
from zoneinfo import ZoneInfo

import httpx

from core.schemas import Evidence, SearchResult, utcnow
from perception.evidence_extractor import EXTRACTION_VERSION, fingerprint, result_id
from perception.search_client import SearchError

NPM_PAGE_URL = (
    "https://fe.secondmarket.com/companies/company-30839e0b-2730-4495-839f-1bf638fa9cca/data"
)
NPM_API_URL = (
    "https://api-npm17-data-company-pricing-review-prod.k8s-prod-1.npmdev.net"
    "/api/public/companies/company-30839e0b-2730-4495-839f-1bf638fa9cca"
)


def fetch_npm_snapshot() -> SearchResult:
    try:
        response = httpx.get(NPM_API_URL, timeout=20)
        response.raise_for_status()
        now = utcnow()
        result = SearchResult(
            title="OpenAI NPM public company pricing snapshot",
            url=NPM_API_URL,
            source=NPM_PAGE_URL,
            published_at=now,
            published_time_basis="retrieval_snapshot; exact publication time not asserted",
            retrieved_at=now,
            content=response.text,
            query="Official NPM OpenAI valuation feed",
        )
        parse_npm_snapshot(result)
        return result
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise SearchError(f"NPM official valuation feed unavailable or invalid: {exc}") from exc


def parse_npm_snapshot(result: SearchResult) -> Evidence:
    if result.url != NPM_API_URL or result.source != NPM_PAGE_URL or result.synthetic:
        raise ValueError("Not the configured official NPM OpenAI feed")
    data = json.loads(result.content)
    if data["company"]["dba_name"] != "OpenAI":
        raise ValueError("NPM feed company is not OpenAI")
    mark = data["latest_npm_price"]
    day = date.fromisoformat(mark["date"])
    price = float(mark["price"])
    usd = float(mark["implied_valuation"])
    if not (isfinite(price) and price > 0 and isfinite(usd) and usd > 0):
        raise ValueError("NPM mark has an invalid price or company valuation")
    event_at = datetime.combine(day, time.min, ZoneInfo("America/New_York"))
    if event_at > result.retrieved_at or not result.published_at:
        raise ValueError("NPM mark date is future or snapshot availability is unknown")
    match = re.search(r'"latest_npm_price":(\{[^{}]+\})', result.content)
    if match is None or json.loads(match.group(1)) != mark:
        raise ValueError("NPM valuation lacks an exact raw source fragment")
    quote = match.group(0)
    return Evidence(
        evidence_id=fingerprint(EXTRACTION_VERSION + result_id(result) + quote),
        document_id=result_id(result),
        extraction_version=EXTRACTION_VERSION,
        support_quote=quote,
        claim_kind="fact",
        event_date_quote=mark["date"],
        event_time_basis="source_date",
        valuation_status="observed",
        title=result.title,
        source_url=NPM_PAGE_URL,
        source=NPM_API_URL,
        published_at=result.published_at,
        published_time_basis=result.published_time_basis,
        retrieved_at=result.retrieved_at,
        event_at=event_at,
        raw_content=result.content,
        claim=(
            f"NPM OpenAI {day.isoformat()} implied valuation USD {usd / 1e9:.9f} billion "
            f"and NPM Price USD {price:.8f} per share."
        ),
        category="valuation",
        confidence=0.9,
        relevance=1,
        impact_direction="neutral",
        reasoning="NPM public feed reports both company implied valuation in USD and price per share.",
        source_type="official",
        epistemic_status="Verified Fact",
        event_key=f"npm-implied-valuation-{day.isoformat()}",
        synthetic=False,
        valuation_usd_billion=usd / 1e9,
        share_price_usd=price,
        valuation_quote=quote,
        valuation_metric="NPM",
    )
