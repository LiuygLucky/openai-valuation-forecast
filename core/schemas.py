"""Validated boundaries for external data, model output and persisted state."""

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Interval(StrictModel):
    label: str
    lower: float = Field(ge=0)
    upper: float | None = Field(default=None, gt=0)


class ResearchItem(StrictModel):
    research_question: str
    rationale: str
    priority: int = Field(ge=1, le=8)
    suggested_queries: list[str] = Field(min_length=1, max_length=4)
    expected_information: str
    category: str = "other"


class ResearchPlan(StrictModel):
    items: list[ResearchItem] = Field(min_length=1, max_length=8)


class SearchResult(StrictModel):
    title: str
    url: str
    source: str
    published_at: AwareDatetime | None = None
    published_time_basis: str = "unknown"
    retrieved_at: AwareDatetime = Field(default_factory=utcnow)
    event_at: AwareDatetime | None = None
    content: str
    query: str
    synthetic: bool = False

    @field_validator("url")
    @classmethod
    def public_url(cls, value):
        from urllib.parse import urlsplit

        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("Source must have a valid HTTP(S) URL")
        return value


class Evidence(StrictModel):
    evidence_id: str
    document_id: str = ""
    extraction_version: str = "legacy"
    support_quote: str = ""
    claim_kind: Literal["fact", "forecast", "rumor", "opinion", "unknown"] = "unknown"
    event_date_quote: str | None = None
    event_time_basis: Literal["source_date", "publication_proxy", "unknown", "synthetic"] = (
        "unknown"
    )
    valuation_status: Literal["completed", "observed", "proposed", "unknown"] = "unknown"
    title: str
    source_url: str
    source: str
    published_at: AwareDatetime | None = None
    published_time_basis: str = "unknown"
    retrieved_at: AwareDatetime
    event_at: AwareDatetime | None = None
    raw_content: str
    claim: str
    category: Literal[
        "valuation",
        "financing",
        "revenue",
        "profitability",
        "competition",
        "technology",
        "regulation",
        "macro",
        "other",
    ]
    confidence: float = Field(ge=0, le=1)
    relevance: float = Field(ge=0, le=1)
    impact_direction: Literal["positive", "negative", "neutral", "mixed"]
    reasoning: str
    source_type: Literal["official", "reporting", "analysis", "social", "unknown"]
    epistemic_status: Literal[
        "Verified Fact", "Reported Claim", "Model Inference", "Assumption", "Unknown"
    ]
    event_key: str
    stale: bool = False
    synthetic: bool = False
    valuation_usd_billion: float | None = Field(default=None, gt=0)
    share_price_usd: float | None = Field(default=None, gt=0)
    valuation_quote: str | None = None
    valuation_metric: str | None = None


class ExtractedClaim(StrictModel):
    result_index: int = Field(ge=0)
    support_quote: str = ""
    claim_kind: Literal["fact", "forecast", "rumor", "opinion", "unknown"] = "unknown"
    event_date: str | None = None
    event_date_quote: str | None = None
    valuation_status: Literal["completed", "observed", "proposed", "unknown"] = "unknown"
    claim: str
    category: Literal[
        "valuation",
        "financing",
        "revenue",
        "profitability",
        "competition",
        "technology",
        "regulation",
        "macro",
        "other",
    ]
    impact_direction: Literal["positive", "negative", "neutral", "mixed"]
    epistemic_status: Literal[
        "Verified Fact", "Reported Claim", "Model Inference", "Assumption", "Unknown"
    ]
    event_key: str
    reasoning: str
    relevance: float = Field(ge=0, le=1)
    valuation_usd_billion: float | None = Field(default=None, gt=0)
    share_price_usd: float | None = Field(default=None, gt=0)
    valuation_quote: str | None = None
    valuation_metric: str | None = None

    @field_validator("claim_kind", mode="before")
    @classmethod
    def normalize_reported_claim_kind(cls, value):
        # The model sometimes puts the epistemic label in this temporal-kind field.
        # Do not promote an ambiguous reported claim to an occurred fact.
        if isinstance(value, str) and value.strip().casefold().replace("_", "-") in (
            "reported claim",
            "reported-claim",
        ):
            return "unknown"
        return value

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category_alias(cls, value):
        aliases = {
            "cost": "profitability",
            "costs": "profitability",
            "compute_costs": "profitability",
            "cash_burn": "profitability",
            "losses": "profitability",
            "funding": "financing",
            "competitive_landscape": "competition",
            "regulatory": "regulation",
            "macroeconomic": "macro",
            "macro_conditions": "macro",
        }
        key = (
            value.strip().lower().replace("-", "_").replace(" ", "_")
            if isinstance(value, str)
            else value
        )
        return aliases.get(key, key) if isinstance(key, str) else key


class Extraction(StrictModel):
    claims: list[ExtractedClaim]


class Hypothesis(StrictModel):
    event: str
    mechanism: list[str] = Field(min_length=2)
    direction: Literal["positive", "negative", "neutral", "mixed"]
    counterarguments: list[str] = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    uncertainties: list[str] = Field(min_length=1)
    priced_in: Literal["likely", "possible", "unlikely", "unknown"]


class Reasoning(StrictModel):
    hypotheses: list[Hypothesis]


class Critique(StrictModel):
    accepted_evidence: list[str]
    disputed_evidence: list[str]
    missing_information: list[str]
    potential_biases: list[str]
    recommended_followup_queries: list[str]
    invalid_settlement_evidence: list[str] = Field(default_factory=list)


class Probability(StrictModel):
    interval: str
    probability: float = Field(ge=0, le=1)


class Forecast(StrictModel):
    question: str
    as_of: AwareDatetime
    target_date: AwareDatetime
    valuation_metric: str
    market_rules_source: str
    forecast_type: Literal["terminal_interval"] = "terminal_interval"
    model_version: str = "v1.4"
    mode: Literal["live", "demo"]
    unit: Literal["USD_billion"] = "USD_billion"
    probabilities: list[Probability]
    baseline_probabilities: list[Probability]
    median_valuation: float
    confidence_interval_90: tuple[float, float]
    key_evidence_ids: list[str]
    main_assumptions: list[str]
    limitations: list[str]

    @model_validator(mode="after")
    def normalized(self):
        for rows in (self.probabilities, self.baseline_probabilities):
            if not rows or abs(sum(p.probability for p in rows) - 1) > 1e-8:
                raise ValueError("Probabilities must sum to one")
        return self


class CognitiveState(StrictModel):
    run_id: str = Field(default_factory=lambda: uuid4().hex)
    question: str
    as_of: AwareDatetime
    target_date: AwareDatetime
    mode: Literal["live", "demo"] = "live"
    task_spec: dict = Field(default_factory=dict)
    coverage: dict = Field(default_factory=dict)
    history_comparison: dict | None = None
    research_plan: list[ResearchItem] = Field(default_factory=list)
    search_results: list[SearchResult] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    retrieved_evidence: list[Evidence] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    causal_relations: list[dict] = Field(default_factory=list)
    critique: Critique | None = None
    information_gaps: list[str] = Field(default_factory=list)
    search_history: list[dict] = Field(default_factory=list)
    processing_history: list[dict] = Field(default_factory=list)
    belief_state: dict = Field(default_factory=dict)
    forecast: Forecast | None = None
    iteration_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    trace: list[str] = Field(default_factory=list)
    usage: dict = Field(default_factory=dict)
    generated_at: AwareDatetime = Field(default_factory=utcnow)
    status: Literal["running", "completed", "failed"] = "running"
    report_path: str | None = None
