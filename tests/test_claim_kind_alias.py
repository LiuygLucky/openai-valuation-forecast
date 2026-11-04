from core.schemas import ExtractedClaim


def test_reported_claim_is_not_promoted_to_fact():
    claim = ExtractedClaim.model_validate(
        {
            "result_index": 0,
            "claim_kind": "reported claim",
            "claim": "A source reported a possible event.",
            "category": "other",
            "impact_direction": "neutral",
            "epistemic_status": "Reported Claim",
            "event_key": "reported-event",
            "reasoning": "Attribution only.",
            "relevance": 0.5,
        }
    )
    assert claim.claim_kind == "unknown"
    assert claim.epistemic_status == "Reported Claim"
