from core.config import Settings


class BudgetExceeded(RuntimeError):
    pass


class Budget:
    """Reserve worst-case request cost BEFORE dispatch, including retries."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.llm_calls = 0
        self.search_calls = 0
        self.embedding_calls = 0
        self.embedding_tokens = 0
        self.reserved_tokens = 0
        self.actual_tokens = 0
        self.usage_reported = False
        self.estimated_cost_usd = 0.0

    def reserve(self, kind: str, tokens: int = 0) -> None:
        s = self.settings
        cost = (
            s.search_usd_per_call
            if kind == "search"
            else tokens
            * (
                s.embedding_usd_per_million_tokens
                if kind == "embedding"
                else s.llm_usd_per_million_tokens
            )
            / 1e6
        )
        if self.estimated_cost_usd + cost > s.budget_usd:
            raise BudgetExceeded("Estimated cost budget exhausted")
        if kind == "search":
            if self.search_calls >= s.max_search_calls:
                raise BudgetExceeded("Search call limit exhausted")
            self.search_calls += 1
        elif kind == "embedding":
            if (
                self.embedding_calls >= s.max_embedding_calls
                or self.reserved_tokens + tokens > s.max_tokens
            ):
                raise BudgetExceeded("Embedding call/token limit exhausted")
            self.embedding_calls += 1
            self.reserved_tokens += tokens
        elif kind == "llm":
            if self.llm_calls >= s.max_llm_calls or self.reserved_tokens + tokens > s.max_tokens:
                raise BudgetExceeded("LLM call/token limit exhausted")
            self.llm_calls += 1
            self.reserved_tokens += tokens
        else:
            raise ValueError("Unknown budget kind")
        self.estimated_cost_usd += cost

    def snapshot(self) -> dict:
        return {k: v for k, v in vars(self).items() if k != "settings"}
