import hashlib
import re
from datetime import date, datetime, time
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from core.schemas import Evidence, Extraction
from perception.dates import explicit_days, normalized_quote

EXTRACTION_VERSION = "v1.5"


def official_npm_share_price(result):
    """Record the dated NPM share price without converting dollars/share to billions."""
    from core.schemas import ExtractedClaim

    host = (urlsplit(result.url).hostname or "").removeprefix("www.")
    if result.synthetic or host != "nasdaqprivatemarket.com":
        return None
    match = re.search(
        r"Nasdaq Private Market estimates that OpenAI price per share was\s*"
        r"\$([\d,]+(?:\.\d+)?)\s+as of\s+"
        r"([A-Z][a-z]+\s+\d{1,2},\s+20\d{2})",
        result.content,
        re.I,
    )
    if not match:
        return None
    day = datetime.strptime(match.group(2), "%B %d, %Y").date()
    return ExtractedClaim(
        result_index=0,
        support_quote=match.group(0),
        claim_kind="fact",
        valuation_status="observed",
        event_date=day.isoformat(),
        event_date_quote=match.group(2),
        claim=match.group(0),
        category="valuation",
        impact_direction="neutral",
        epistemic_status="Verified Fact",
        event_key=f"npm-share-price-{day.isoformat()}",
        reasoning="NPM Price is USD per share; whole-company valuation requires separate evidence.",
        relevance=1,
        share_price_usd=float(match.group(1).replace(",", "")),
        valuation_metric="NPM_price_per_share",
    )


def official_forge_anchor(result):
    """Extract only a dated OpenAI Forge Price Valuation from Forge's own text."""
    from core.schemas import ExtractedClaim

    host = (urlsplit(result.url).hostname or "").removeprefix("www.")
    if result.synthetic or host != "forgeglobal.com" or "openai" not in result.content.casefold():
        return None
    pattern = (
        r"OpenAI['’]s?\s+Forge Price(?:\s+valuation)?\s*(?:is|:|was)\s*"
        r"(?:\$[\d,.]+\s*(?:per share|/share)?\s+at\s+an?\s+)?"
        r"\$([\d,.]+)\s*(billion|trillion|bn|tn)\s+valuation\s+"
        r"as of\s+([A-Z][a-z]+\s+\d{1,2},\s+20\d{2})"
    )
    match = re.search(pattern, result.content, re.I)
    if not match:
        return None
    quote = match.group(0)
    day = datetime.strptime(match.group(3), "%B %d, %Y").date()
    return ExtractedClaim(
        result_index=0,
        support_quote=quote,
        claim_kind="fact",
        valuation_status="observed",
        event_date=day.isoformat(),
        event_date_quote=match.group(3),
        claim=quote,
        category="valuation",
        impact_direction="neutral",
        epistemic_status="Verified Fact",
        event_key=f"forge-price-valuation-{day.isoformat()}",
        reasoning="Forge's dated indicative valuation observation, not a financing close or executed trade.",
        relevance=1,
        valuation_usd_billion=float(match.group(1).replace(",", ""))
        * (1000 if match.group(2).lower() in ("trillion", "tn") else 1),
        valuation_quote=quote,
        valuation_metric="Forge",
    )


def official_closed_anchor(result):
    """Narrow literal parser for first-party completed financing announcements.

    Never infer a value from money raised or proposed rounds. Other transaction
    phrasings continue through the language model and independent validation.
    """
    from core.schemas import ExtractedClaim

    if (
        result.synthetic
        or source_quality(result.url)[0] != "official"
        or "openai.com" != (urlsplit(result.url).hostname or "").removeprefix("www.")
    ):
        return None
    pattern = (
        r"(?:Today,?\s+)?we closed our (?:latest |new )?funding round[^\n.!?]*?"
        r"(?:post[- ]money |equity )?valuation of\s*\$(\d[\d,]*(?:\.\d+)?)\s*(billion|trillion)\b[^\n.!?]*[.!?]?"
    )
    match = re.search(pattern, result.content, re.I)
    if not match:
        return None
    quote = match.group(0)
    return ExtractedClaim(
        result_index=0,
        support_quote=quote,
        claim_kind="fact",
        valuation_status="completed",
        claim=quote,
        category="financing",
        impact_direction="positive",
        epistemic_status="Verified Fact",
        event_key="completed-financing-" + str(result.published_at),
        reasoning="Official completed financing observation; serves as valuation anchor, not a second event shift.",
        relevance=1,
        valuation_usd_billion=float(match.group(1).replace(",", ""))
        * (1000 if match.group(2).lower() == "trillion" else 1),
        valuation_quote=quote,
        valuation_metric="financing_proxy",
    )


def canonical_url(url: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), "", ""))


def fingerprint(text: str) -> str:
    return hashlib.sha256(re.sub(r"\W+", "", text.casefold()).encode()).hexdigest()[:24]


def source_quality(url: str) -> tuple[str, float]:
    host = urlsplit(url).hostname or ""

    def matches(domain):
        return host == domain or host.endswith("." + domain)

    if any(
        matches(d)
        for d in (
            "openai.com",
            "microsoft.com",
            "softbank.jp",
            "group.softbank",
            "sec.gov",
            "federalreserve.gov",
        )
    ):
        return "official", 0.9
    if matches("forgeglobal.com"):
        return "official", 0.9
    if matches("nasdaqprivatemarket.com"):
        return "official", 0.9
    if "/opinion/" in url or any(matches(d) for d in ("substack.com", "seekingalpha.com")):
        return "analysis", 0.45
    if any(matches(d) for d in ("reuters.com", "ft.com", "bloomberg.com", "wsj.com")):
        return "reporting", 0.8
    if any(matches(d) for d in ("x.com", "reddit.com", "linkedin.com")):
        return "social", 0.25
    return "unknown", 0.45


def result_id(result) -> str:
    return fingerprint(canonical_url(result.url) + result.content + str(result.published_at))


def validate_valuation(c, r):
    value = c.valuation_usd_billion
    if c.share_price_usd is not None:
        if not re.search(r"price per share[^.]{0,80}\$\s*[\d,.]+", c.support_quote, re.I):
            raise ValueError("Share price must be supported by a per-share USD quote")
        quoted = re.search(
            r"price per share[^.]{0,80}\$\s*([\d,]+(?:\.\d+)?)", c.support_quote, re.I
        )
        if (
            quoted is None
            or abs(float(quoted.group(1).replace(",", "")) - c.share_price_usd) > 1e-6
        ):
            raise ValueError("Share price value differs from source quote")
        if value is not None:
            raise ValueError("Share price and company valuation must be separate observations")
    if value is not None:
        if not c.valuation_quote or not normalized_quote(c.valuation_quote, r.content):
            raise ValueError("Valuation anchor quote not found in original source")
        if not re.search(r"USD|US\$|\$|美元|U\.?S\.? dollars", c.valuation_quote, re.I):
            raise ValueError("Valuation quote must explicitly establish USD currency")
        if "openai" not in r.content.casefold():
            raise ValueError("Valuation source does not identify OpenAI")
        if not r.synthetic:
            if re.search(
                r"(?:stake|investment|holding)[^.]{0,100}(?:valued|worth|valuation)",
                c.support_quote,
                re.I,
            ):
                raise ValueError("A shareholder stake value is not the whole-company valuation")
            valuation_amounts = re.findall(
                r"(?:valuation(?:\s+of|\s+at)?|valued\s+at)\s*(?:approximately\s*|about\s*)?(?:USD\s*|US\$\s*|\$\s*)(\d[\d,]*(?:\.\d+)?)\s*(billion|trillion|bn|tn)\b",
                c.valuation_quote,
                re.I,
            )
            if c.valuation_metric == "Forge":
                valuation_amounts += re.findall(
                    r"\$\s*(\d[\d,]*(?:\.\d+)?)\s*(billion|trillion|bn|tn)\s+valuation",
                    c.valuation_quote,
                    re.I,
                )
            if not any(
                abs(
                    float(n.replace(",", "")) * (1000 if unit.lower() in ("trillion", "tn") else 1)
                    - value
                )
                < 1e-6
                for n, unit in valuation_amounts
            ):
                raise ValueError(
                    "Quote must associate this amount explicitly with valuation, not money raised"
                )
        # Check number/unit conversion independently from the language model.
        matches = re.findall(
            r"(\d[\d,]*(?:\.\d+)?)\s*(trillion\b|billion\b|million\b|trn\b|bn\b|tn\b|b\b|t\b|m\b|万亿|十亿|亿)",
            c.valuation_quote,
            re.I,
        )
        factors = {
            "trillion": 1000,
            "billion": 1,
            "million": 0.001,
            "万亿": 1000,
            "十亿": 1,
            "亿": 0.1,
            "bn": 1,
            "b": 1,
            "trn": 1000,
            "tn": 1000,
            "t": 1000,
            "m": 0.001,
        }
        if not any(
            abs(float(n.replace(",", "")) * factors[u.lower()] - value) < 1e-6 for n, u in matches
        ):
            raise ValueError("Valuation value/unit inconsistent with source quote")


def extract(
    results,
    llm,
    as_of,
    stale_days=180,
    excerpt_chars=5000,
    *,
    strict=True,
    warnings=None,
    source_timezone="America/New_York",
) -> list[Evidence]:
    unique = {}
    for r in results:
        if r.published_at and r.published_at > as_of:
            continue
        unique.setdefault((canonical_url(r.url), fingerprint(r.content)), r)
    docs = list(unique.values())
    if not docs:
        return []
    extraction = llm.generate(
        Extraction,
        "Extract relevant claims. result_index MUST index the supplied results. Group syndicated copies "
        "under the same event_key. Do not infer publication dates. Only extract valuation if the text "
        "explicitly states an actual OpenAI equity transaction/quote, a dated Forge Price Valuation, or an NPM Price per share. Never treat a per-share price as a USD-billion company valuation; not a target, enterprise value, "
        "rumor, competitor valuation or amount raised. valuation_quote MUST be an exact substring "
        "containing the value AND USD currency; NEVER translate or paraphrase the quote. valuation_metric is financing_proxy, NPM or Forge. "
        "Every claim needs support_quote copied verbatim from content. It must substantiate the specific claim, not just match numbers. "
        "Classify claim_kind: fact (occurred or signed commitment), forecast (forward-looking projection), rumor, opinion, unknown. "
        "For a financing anchor valuation_status MUST be completed; for a Forge Price Valuation observation use observed. Never treat a proposed round as observed. "
        "valuation_quote should be a sentence showing OpenAI's valuation and completed transaction, not the funding amount. "
        "Set event_date to YYYY-MM-DD ONLY when a full date is explicitly present; copy that date's original context "
        "into event_date_quote. Leave null for unknown or month-only dates. Distinguish event date from publication. "
        "Reported journalism remains Reported Claim, not Verified Fact. Extract one or two important claims from EACH relevant document, "
        "covering revenue, costs, cash burn and competition as well as financing. Forecast cost figures are valid forecast claims "
        "even though they cannot be valuation anchors. Do not skip supported operating claims merely because no transaction occurred. "
        "Quotes MUST preserve the source's original language, punctuation and wording, including post money vs post-money.",
        {
            "results": [
                r.model_dump(mode="json") | {"content": r.content[:excerpt_chars]} for r in docs
            ]
        },
    )
    for index, doc in enumerate(docs):
        anchor_claim = (
            official_closed_anchor(doc)
            or official_forge_anchor(doc)
            or official_npm_share_price(doc)
        )
        if anchor_claim:
            anchor_claim.result_index = index
            extraction.claims = [
                c
                for c in extraction.claims
                if not (c.result_index == index and c.valuation_usd_billion)
            ]
            extraction.claims.append(anchor_claim)
    evidence = []
    for c in extraction.claims:
        if c.result_index >= len(docs):
            raise ValueError("LLM referenced a nonexistent search result")
        r = docs[c.result_index]
        source_type, confidence = source_quality(r.url)
        value = c.valuation_usd_billion
        try:
            if not r.synthetic and not normalized_quote(c.support_quote, r.content):
                raise ValueError("Claim support quote not found in original source")
            validate_valuation(c, r)
            if (
                value is not None
                and not r.synthetic
                and (
                    c.claim_kind != "fact"
                    or (
                        (c.valuation_metric == "Forge" and c.valuation_status != "observed")
                        or (c.valuation_metric != "Forge" and c.valuation_status != "completed")
                    )
                )
            ):
                raise ValueError(
                    "Valuation anchor must be a completed transaction or observed Forge mark"
                )
        except ValueError as exc:
            if strict:
                raise
            if warnings is not None:
                warnings.append(f"Rejected extracted evidence from {r.url}: {exc}")
            continue
        event_at = r.event_at
        event_basis = "synthetic" if r.synthetic and event_at else "unknown"
        if c.event_date:
            try:
                day = date.fromisoformat(c.event_date)
                if (
                    not c.event_date_quote
                    or not normalized_quote(c.event_date_quote, r.content)
                    or day not in explicit_days(c.event_date_quote)
                ):
                    raise ValueError("Event date lacks a matching explicit source date")
                event_at = datetime.combine(day, time.min, ZoneInfo(source_timezone))
                event_basis = "source_date"
            except ValueError as exc:
                # Preserve a sourced claim but do not invent an unsupported event date.
                if warnings is not None:
                    warnings.append(f"Event date quarantined for {r.url}: {exc}")
                event_at, event_basis = None, "unknown"
        if c.claim_kind == "fact" and event_at and event_at > as_of:
            if strict:
                raise ValueError("Future event mislabeled as occurred fact")
            if warnings is not None:
                warnings.append(f"Rejected future occurred fact from {r.url}")
            continue
        status = c.epistemic_status
        if status == "Verified Fact" and source_type != "official":
            status = "Reported Claim"
        evidence.append(
            Evidence(
                evidence_id=fingerprint(EXTRACTION_VERSION + result_id(r) + c.event_key + c.claim),
                document_id=result_id(r),
                extraction_version=EXTRACTION_VERSION,
                support_quote=c.support_quote,
                claim_kind=c.claim_kind,
                valuation_status=c.valuation_status,
                event_date_quote=c.event_date_quote if event_basis == "source_date" else None,
                event_time_basis=event_basis,
                title=r.title,
                source_url=r.url,
                source=r.source,
                published_at=r.published_at,
                published_time_basis=r.published_time_basis,
                retrieved_at=r.retrieved_at,
                event_at=event_at,
                raw_content=r.content,
                claim=c.claim,
                category=c.category,
                confidence=confidence,
                relevance=c.relevance,
                impact_direction=c.impact_direction,
                reasoning=c.reasoning,
                source_type=source_type,
                epistemic_status=status,
                event_key=c.event_key,
                stale=bool(r.published_at and (as_of - r.published_at).days > stale_days),
                synthetic=r.synthetic,
                valuation_usd_billion=value,
                share_price_usd=c.share_price_usd,
                valuation_quote=c.valuation_quote,
                valuation_metric=c.valuation_metric,
            )
        )
    return evidence
