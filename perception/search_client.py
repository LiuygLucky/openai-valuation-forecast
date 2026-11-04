import os
import re
from datetime import date, datetime, time, timezone
from email.utils import parsedate_to_datetime
from typing import Protocol
from urllib.parse import urlparse

import httpx

from core.budget import Budget, BudgetExceeded
from core.schemas import SearchResult, utcnow
from perception.dates import explicit_days


class SearchError(RuntimeError):
    pass


class SearchClient(Protocol):
    def search(self, query: str) -> list[SearchResult]: ...


def parse_date(value) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(str(value))
        except (ValueError, TypeError):
            return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def publication_time(result):
    supplied = parse_date(result.get("published_date"))
    if supplied:
        return supplied, "search_provider"
    # Dated Reuters article URL must agree with an explicit source date.
    # End-of-day UTC is a conservative availability proxy, not an exact timestamp.
    url = urlparse(result.get("url", ""))
    match = re.search(r"-(20\d{2}-\d{2}-\d{2})/?$", url.path)
    if (url.hostname or "").removeprefix("www.") == "reuters.com" and match:
        day = date.fromisoformat(match.group(1))
        body = (result.get("content") or "") + "\n" + (result.get("raw_content") or "")
        if day in explicit_days(body):
            return datetime.combine(
                day, time(23, 59, 59), timezone.utc
            ), "article_url_and_explicit_source_day; conservative_end_of_day_UTC"
    return None, "unknown"


class TavilySearch:
    def __init__(self, budget: Budget):
        self.budget = budget
        self.request_history = []
        self.key = os.getenv("TAVILY_API_KEY")
        if not self.key:
            raise SearchError("Missing TAVILY_API_KEY: configure .env or explicitly use --demo")

    def search(self, query: str, *, _topic=None) -> list[SearchResult]:
        topic = _topic or self.budget.settings.search_topic
        if topic == "auto":
            topic = (
                "general"
                if any(w in query.lower() for w in ("cash", "cost", "loss", "spend"))
                else "news"
            )
        for attempt in range(self.budget.settings.search_retries + 1):
            self.budget.reserve("search")
            try:
                response = httpx.post(
                    "https://api.tavily.com/search",
                    headers={"Authorization": f"Bearer {self.key}"},
                    json={
                        "query": query,
                        "search_depth": "basic",
                        "topic": topic,
                        "max_results": self.budget.settings.search_results,
                        "include_raw_content": True,
                        "include_answer": False,
                        **(
                            {"include_domains": re.findall(r"site:([a-zA-Z0-9.-]+)", query)}
                            if "site:" in query
                            else {}
                        ),
                    },
                    timeout=30,
                )
                response.raise_for_status()
                now = utcnow()
                results = [
                    SearchResult(
                        title=r["title"],
                        url=r["url"],
                        source=urlparse(r["url"]).netloc,
                        published_at=publication_time(r)[0],
                        published_time_basis=publication_time(r)[1],
                        retrieved_at=now,
                        # Query-focused snippet first: raw pages often begin with navigation.
                        content="\n\n".join(
                            dict.fromkeys(filter(None, [r.get("content"), r.get("raw_content")]))
                        )[:12000],
                        query=query,
                    )
                    for r in response.json()["results"]
                    if r.get("content") or r.get("raw_content")
                ]
                self.request_history.append(
                    {"query": query, "topic": topic, "count": len(results), "time": now.isoformat()}
                )
                if topic == "general" and _topic is None:
                    candidate = next(
                        (
                            r
                            for r in results
                            if r.published_at is None
                            and "openai" in r.title.lower()
                            and (urlparse(r.url).hostname or "").removeprefix("www.")
                            == "reuters.com"
                        ),
                        None,
                    )
                    if candidate:
                        day = re.search(r"20\d{2}-\d{2}-\d{2}", candidate.url)
                        metadata_query = (
                            f"{candidate.title} {day.group() if day else ''} site:reuters.com"
                        )
                        try:
                            metadata = self.search(metadata_query, _topic="news")
                        except (SearchError, BudgetExceeded):
                            metadata = []  # Original undated items stay undated and cannot pass review.
                        if metadata:
                            from perception.evidence_extractor import canonical_url

                            dated = {canonical_url(r.url): r for r in metadata if r.published_at}
                            results = [dated.get(canonical_url(r.url), r) for r in results]
                return results
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                if attempt == self.budget.settings.search_retries:
                    raise SearchError(
                        "Tavily request failed after bounded retries; no synthetic fallback"
                    ) from None
        return []
