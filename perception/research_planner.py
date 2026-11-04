from core.schemas import ResearchItem, ResearchPlan


def plan_research(llm, question, rules, as_of=None, evidence=None):
    result = llm.generate(
        ResearchPlan,
        "Plan research for TERMINAL OpenAI equity valuation, NOT a barrier/hit-before-date event. "
        "Cover the configured provider's dated valuation observation, completed financing, revenue/profitability, compute costs, competition, "
        "regulation and macro conditions. Include disconfirming information. "
        "Priority 1 is most urgent; use focused externally searchable queries. "
        "Use as_of as the current information date, NOT your training cutoff. "
        "Do not anchor queries to obsolete years. First query per item must be useful by itself. "
        "Prefer primary announcements or direct Reuters/FT reporting for completed transactions. "
        "Do not confuse money raised, targeted valuation, completed financing and completed IPO. "
        "Set category for each item: financing, revenue, profitability, competition, macro, regulation. "
        "Prioritize valuation anchor, operating growth, and downside costs across the first three items. "
        "Use available public reporting; do not search for nonpublic OpenAI audited SEC financial statements. "
        "Use existing evidence summaries to target genuinely missing facts.",
        {
            "question": question,
            "as_of": str(as_of),
            "rules": rules.model_dump(mode="json"),
            "known_evidence": [
                {"category": e.category, "claim": e.claim, "date": str(e.published_at)}
                for e in (evidence or [])[:12]
            ],
        },
    )
    ordered = sorted(result.items, key=lambda item: item.priority)
    selected = []
    year = as_of.year if as_of else rules.target_date.year
    fallbacks = {
        "financing": (
            f"OpenAI Forge Price valuation as of {year} site:forgeglobal.com"
            if rules.provider == "Forge"
            else f"OpenAI NPM Price implied valuation {year} site:nasdaqprivatemarket.com/company/open-ai"
            if rules.provider == "NPM"
            else f"OpenAI latest completed funding round valuation {year} site:openai.com"
        ),
        "revenue": f"OpenAI revenue growth enterprise customers {year} site:reuters.com",
        "profitability": f"OpenAI cash burn forecast {year} site:reuters.com",
    }
    for category, query in fallbacks.items():
        item = next((p for p in ordered if p.category == category), None)
        if item is None:
            item = ResearchItem(
                research_question=query,
                rationale="Required coverage guardrail",
                priority=1,
                suggested_queries=[query],
                expected_information="Dated public evidence",
                category=category,
            )
        # Reserve one short, publisher-filtered query per required factor. Keep the
        # model's more specific questions for follow-up rather than losing coverage.
        item.suggested_queries = list(dict.fromkeys([query] + item.suggested_queries))[:4]
        selected.append(item)
    return selected + [p for p in ordered if p not in selected]


def diverse_queries(items):
    """Round-robin across research questions before taking second queries for any topic."""
    return list(
        dict.fromkeys(
            item.suggested_queries[i]
            for i in range(max((len(item.suggested_queries) for item in items), default=0))
            for item in items
            if i < len(item.suggested_queries)
        )
    )


def document_topic(query):
    query = query.lower()
    return next(
        (
            name
            for name, words in (
                ("profitability", ("cash burn", "cash flow", "cost", "loss", "spend")),
                ("revenue", ("revenue", "customer")),
                ("financing", ("funding", "financing", "valuation")),
                ("competition", ("competition", "market share")),
            )
            if any(word in query for word in words)
        ),
        "other",
    )


def document_priority(doc, topic):
    """Source authority alone must not rank an unrelated company page above a cost report."""
    from perception.evidence_extractor import source_quality

    terms = {
        "profitability": ("cash burn", "cash flow", "loss", "cost", "spend", "compute"),
        "revenue": ("revenue", "sales", "paying", "customer"),
        "financing": ("funding", "financing", "valuation", "raises", "closed"),
        "competition": ("competition", "compete", "market share", "rival"),
    }.get(topic, ())
    title = doc.title.lower()
    score = sum(4 for term in terms if term in title) + sum(
        1 for term in terms if term in doc.content[:800].lower()
    )
    quality = source_quality(doc.url)[1]
    return (
        -int(any(term in title for term in terms)),
        -int(quality >= 0.75),
        doc.published_at is None,
        -int("openai" in title),
        -(doc.published_at.timestamp() if doc.published_at else 0),
        -score,
        -quality,
    )
