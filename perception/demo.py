"""SYNTHETIC fixtures, never returned by the live search adapter."""

from datetime import timedelta

from core.schemas import (
    Critique,
    ExtractedClaim,
    Extraction,
    Hypothesis,
    Reasoning,
    ResearchItem,
    ResearchPlan,
    SearchResult,
)


class DemoSearch:
    def __init__(self, as_of, provider="financing_proxy"):
        self.as_of = as_of
        self.provider = provider

    def search(self, query: str) -> list[SearchResult]:
        fixtures = [
            (
                "financing",
                "SYNTHETIC OpenAI Forge Price Valuation is USD 500 billion."
                if self.provider == "Forge"
                else "SYNTHETIC OpenAI NPM implied company valuation is USD 500 billion."
                if self.provider == "NPM"
                else "SYNTHETIC OpenAI financing valued equity at USD 500 billion.",
                "positive",
            ),
            (
                "revenue",
                "SYNTHETIC enterprise subscription revenue increased; no actual financial disclosure.",
                "positive",
            ),
            (
                "profitability",
                "SYNTHETIC compute commitments raised costs and financing needs.",
                "negative",
            ),
            (
                "competition",
                "SYNTHETIC competitors cut prices, creating margin pressure.",
                "negative",
            ),
        ]
        return [
            SearchResult(
                title=f"DEMO / SYNTHETIC {cat}",
                url=f"https://{cat}.synthetic.invalid/{cat}",
                source=f"{cat}.synthetic.invalid",
                published_at=self.as_of - timedelta(days=10 if i == 0 else 5 + i),
                retrieved_at=self.as_of,
                event_at=self.as_of - timedelta(days=11 if i == 0 else 6 + i),
                content=content,
                query=query,
                synthetic=True,
            )
            for i, (cat, content, _) in enumerate(fixtures)
        ]


class DemoLLM:
    """Deterministic test double; not a claim of an actual LLM invocation."""

    def __init__(self, provider="financing_proxy"):
        self.provider = provider

    def generate(self, schema, instruction, context):
        if schema is ResearchPlan:
            return ResearchPlan(
                items=[
                    ResearchItem(
                        research_question=q,
                        rationale="DEMO coverage of key valuation drivers",
                        priority=i + 1,
                        suggested_queries=[q],
                        expected_information="Timestamped sourced facts",
                        category=["financing", "revenue", "profitability"][i],
                    )
                    for i, q in enumerate(
                        [
                            "OpenAI financing valuation",
                            "OpenAI revenue compute costs",
                            "OpenAI competition regulatory risks",
                        ]
                    )
                ]
            )
        if schema is Extraction:
            rows = []
            for i, r in enumerate(context["results"]):
                cat = r["url"].rsplit("/", 1)[-1]
                rows.append(
                    ExtractedClaim(
                        result_index=i,
                        support_quote=r["content"],
                        claim_kind="fact",
                        valuation_status=(
                            "observed" if self.provider in ("Forge", "NPM") else "completed"
                        )
                        if cat == "financing"
                        else "unknown",
                        claim=r["content"],
                        category=cat,
                        impact_direction="positive"
                        if cat in ("financing", "revenue")
                        else "negative",
                        epistemic_status="Assumption",
                        event_key="synthetic-" + cat,
                        reasoning="SYNTHETIC test fixture, not a real fact",
                        relevance=1,
                        valuation_usd_billion=500 if cat == "financing" else None,
                        valuation_quote="USD 500 billion" if cat == "financing" else None,
                        valuation_metric=self.provider if cat == "financing" else None,
                    )
                )
            return Extraction(claims=rows)
        if schema is Reasoning:
            return Reasoning(
                hypotheses=[
                    Hypothesis(
                        event=e["claim"],
                        mechanism=[
                            e["category"],
                            "Changes expected future cash flows or required return",
                            "May change terminal equity valuation",
                        ],
                        direction=e["impact_direction"],
                        counterarguments=["Effect may already be priced in"],
                        evidence_ids=[e["evidence_id"]],
                        uncertainties=["Impact magnitude is not calibrated"],
                        priced_in="possible",
                    )
                    for e in context["evidence"]
                ]
            )
        if schema is Critique:
            return Critique(
                accepted_evidence=[e["evidence_id"] for e in context["evidence"]],
                disputed_evidence=[],
                missing_information=["No verified NPM/Forge terminal settlement quote"],
                potential_biases=["SYNTHETIC fixtures cannot establish real predictive accuracy"],
                recommended_followup_queries=["OpenAI NPM Forge valuation quote methodology"],
            )
        raise TypeError(f"Unsupported demo schema: {schema}")
