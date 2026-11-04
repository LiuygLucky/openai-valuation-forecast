from core.schemas import Reasoning


def reason(llm, evidence, question, as_of=None):
    result = llm.generate(
        Reasoning,
        "Produce causal MECHANISM HYPOTHESES, not identified causal effects. For each important "
        "event explain intermediate variables, direction, priced-in risk, contrary explanations, "
        "uncertainties and exact evidence_ids. No unsupported numerical probabilities. "
        "One hypothesis per distinct real-world event; do not double count syndication or collapse unrelated revenue and cost events into one neutral hypothesis. "
        "as_of is the information cutoff; the question's target date is still in the future.",
        {
            "question": question,
            "as_of": str(as_of),
            "evidence": [e.model_dump(mode="json", exclude={"raw_content"}) for e in evidence],
        },
    )
    known = {e.evidence_id for e in evidence}
    for h in result.hypotheses:
        if not set(h.evidence_ids) <= known:
            raise ValueError("Causal hypothesis contains unknown evidence IDs")
    return result.hypotheses
