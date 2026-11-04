from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv
from pydantic import AwareDatetime, Field, model_validator

from core.schemas import Interval, StrictModel

ROOT = Path(__file__).resolve().parents[1]


class Settings(StrictModel):
    max_iterations: int = Field(default=2, ge=1, le=5)
    queries_per_round: int = Field(default=3, ge=1, le=8)
    max_search_calls: int = Field(default=9, ge=1, le=100)
    max_llm_calls: int = Field(default=10, ge=1, le=100)
    max_tokens: int = Field(default=250000, ge=100)
    max_output_tokens: int = Field(default=4000, ge=100)
    budget_usd: float = Field(default=2, gt=0)
    llm_usd_per_million_tokens: float = Field(default=5, gt=0)
    search_usd_per_call: float = Field(default=0.02, gt=0)
    search_retries: int = Field(default=1, ge=0, le=3)
    search_results: int = Field(default=5, ge=1, le=10)
    search_topic: Literal["general", "news", "auto"] = "auto"
    max_documents_per_round: int = Field(default=8, ge=1, le=20)
    document_excerpt_chars: int = Field(default=5000, ge=1000, le=12000)
    retrieval_k: int = Field(default=16, ge=1, le=50)
    embedding_model: str = "hashing-char-1024"
    max_embedding_calls: int = Field(default=20, ge=1, le=100)
    embedding_usd_per_million_tokens: float = Field(default=1.0, gt=0)
    embedding_cache: str = "data/embeddings.sqlite"
    max_anchor_age_days: int = Field(default=1095, ge=1)
    anchor_age_log_sigma: float = Field(default=0.15, ge=0, le=1)
    unknown_event_date_log_sigma: float = Field(default=0.10, ge=0, le=1)
    min_sources: int = Field(default=2, ge=2)
    min_categories: int = Field(default=3, ge=3)
    seed: int = 42
    samples: int = Field(default=50000, ge=1000, le=1000000)
    annual_log_volatility: float = Field(default=0.5, gt=0, le=2)
    annual_log_drift: float = Field(default=0, ge=-1, le=1)
    proxy_extra_log_sigma: float = Field(default=0.2, ge=0, le=1)
    max_total_log_shift: float = Field(default=0.25, ge=0, le=1)
    event_log_shift: float = Field(default=0.025, ge=0, le=0.1)
    stale_days: int = Field(default=180, ge=1)
    database: str = "data/forecast.sqlite"
    output_dir: str = "reports/runs"


class MarketRules(StrictModel):
    forecast_type: Literal["terminal_interval"]
    target_date: AwareDatetime
    valuation_metric: str
    unit: Literal["USD_billion"]
    timezone: str
    rules_status: str
    market_rules_source: str = Field(min_length=10)
    provider: Literal["financing_proxy", "NPM", "Forge"]
    missing_data_rule: str
    ipo_rule: str
    update_rule: str
    boundary_rule: str
    intervals: list[Interval] = Field(min_length=2)

    @model_validator(mode="after")
    def valid_partition(self):
        ZoneInfo(self.timezone)
        if self.intervals[0].lower != 0 or self.intervals[-1].upper is not None:
            raise ValueError("Intervals must cover [0, infinity)")
        if len({x.label for x in self.intervals}) != len(self.intervals):
            raise ValueError("Interval labels must be unique")
        for i, item in enumerate(self.intervals):
            if item.upper is not None and item.upper <= item.lower:
                raise ValueError("Empty or reversed interval")
            if i < len(self.intervals) - 1 and item.upper != self.intervals[i + 1].lower:
                raise ValueError("Overlapping or missing interval")
        return self


def load_config(settings_path=None, rules_path=None) -> tuple[Settings, MarketRules]:
    load_dotenv(ROOT / ".env")
    settings = Settings.model_validate(
        yaml.safe_load(
            Path(settings_path or ROOT / "config/settings.yaml").read_text(encoding="utf-8")
        )
    )
    rules = MarketRules.model_validate(
        yaml.safe_load(
            Path(rules_path or ROOT / "config/market_rules.yaml").read_text(encoding="utf-8")
        )
    )
    return settings, rules
