import numpy as np
import pytest
from pydantic import ValidationError

from belief.distribution import interval_probabilities, simulate
from core.budget import Budget, BudgetExceeded
from core.config import Settings, load_config
from core.schemas import ResearchPlan
from perception.search_client import SearchError, TavilySearch


def test_config_and_probabilities():
    settings, rules = load_config()
    baseline, posterior = simulate(500, 0.2, settings)
    assert np.array_equal(baseline, posterior)
    assert np.array_equal(posterior, simulate(500, 0.2, settings)[1])
    assert sum(
        x.probability for x in interval_probabilities(posterior, rules.intervals)
    ) == pytest.approx(1)


def test_schema_rejects_bad_llm():
    with pytest.raises(ValidationError):
        ResearchPlan.model_validate({"items": [{"priority": 99}]})


def test_missing_search_key(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    with pytest.raises(SearchError, match="Missing"):
        TavilySearch(Budget(Settings()))


def test_search_failure_bounded(monkeypatch):
    import httpx

    monkeypatch.setenv("TAVILY_API_KEY", "test")

    def fail(*args, **kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "post", fail)
    budget = Budget(Settings(search_retries=1))
    with pytest.raises(SearchError, match="bounded retries"):
        TavilySearch(budget).search("test")
    assert budget.search_calls == 2


def test_budget_blocks_before_dispatch():
    budget = Budget(Settings(max_llm_calls=1))
    budget.reserve("llm", 100)
    with pytest.raises(BudgetExceeded):
        budget.reserve("llm", 100)
