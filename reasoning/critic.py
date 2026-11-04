import re
from difflib import SequenceMatcher

from core.schemas import Critique
from perception.evidence_extractor import fingerprint
from perception.npm_official import NPM_API_URL, NPM_PAGE_URL


def event_groups(evidence):
    """Group exact/near syndicated content and model-normalized event keys."""
    groups = []
    for e in sorted(evidence, key=lambda x: (-x.confidence, x.evidence_id)):
        for group in groups:
            other = group[0]
            if (
                e.valuation_metric == other.valuation_metric == "NPM"
                and e.event_at is not None
                and other.event_at is not None
                and e.event_at.date() != other.event_at.date()
            ):
                continue
            if (
                e.event_key.casefold() == other.event_key.casefold()
                or (
                    e.claim_kind == other.claim_kind
                    and normalized_event_key(e.event_key) == normalized_event_key(other.event_key)
                )
                or (
                    e.category == other.category
                    and (
                        fingerprint(e.raw_content) == fingerprint(other.raw_content)
                        or SequenceMatcher(
                            None, e.raw_content.casefold(), other.raw_content.casefold()
                        ).ratio()
                        > 0.88
                    )
                )
            ):
                group.append(e)
                break
        else:
            groups.append([e])
    return groups


def normalized_event_key(value):
    # Normalize formatting and reporting qualifiers, while retaining time windows
    # and substantive tokens. A forecast and a realized fact remain distinct.
    terms = re.findall(r"[a-z0-9]+", value.casefold())
    return tuple(
        sorted(
            term
            for term in terms
            if term not in {"forecast", "projection", "projections", "reported", "announcement"}
        )
    )


def critique(llm, evidence, hypotheses, as_of=None):
    result = llm.generate(
        Critique,
        "Independently audit evidence. Identify contradictory claims, one-sided search, rumor "
        "treated as fact, duplicate events, causal overclaims, missing negative factors, and "
        "missing fundamental variables. accepted_evidence and disputed_evidence must use "
        "supplied IDs. Put evidence confirming an ALREADY COMPLETED IPO or other invalidation "
        "of the private valuation metric in invalid_settlement_evidence; proposed IPOs are not "
        "completed IPOs. as_of is the information cutoff, NOT the future target date. "
        "Provide SHORT focused search queries for material gaps; prioritize a direct official or "
        "Reuters announcement of the latest COMPLETED transaction if the anchor is missing. "
        "Do not require private/internal documents unavailable to public search. "
        "Old completed financing is valid historical evidence, not a current quote: do NOT dispute solely for age; "
        "the numerical model propagates its age-dependent uncertainty. Report forecasts as forecasts, not realized outcomes. "
        "Financing proxy is allowed; no Forge/NPM quote or completed IPO is required. "
        "Accepted means usable evidence of a sourced statement, NOT independently audited truth. "
        "Company-reported revenue and Reuters-reported projections may be accepted with their explicit epistemic labels. "
        "Do not require audited private financials or an official confirmation of every reported claim; record those limits as uncertainty. "
        "Do not reject time-stamped sources solely because they postdate your pretrained knowledge. "
        "List every supplied evidence ID as accepted or disputed; do not silently omit claims. "
        "Distinguish historical periods and a shareholder's stake value from whole-company valuation.",
        {
            "as_of": str(as_of),
            "evidence": [e.model_dump(mode="json", exclude={"raw_content"}) for e in evidence],
            "hypotheses": [h.model_dump() for h in hypotheses],
        },
    )
    known = {e.evidence_id for e in evidence}
    if (
        not (
            set(result.accepted_evidence)
            | set(result.disputed_evidence)
            | set(result.invalid_settlement_evidence)
        )
        <= known
    ):
        raise ValueError("Critic returned unknown evidence IDs")
    disputed = set(result.disputed_evidence)
    for group in event_groups(evidence):
        values = {e.valuation_usd_billion for e in group if e.valuation_usd_billion is not None}
        disputed.update(e.evidence_id for e in (group if len(values) > 1 else group[1:]))
    for e in evidence:
        if e.published_at is None or (
            not e.synthetic and e.epistemic_status in ("Assumption", "Unknown", "Model Inference")
        ):
            disputed.add(e.evidence_id)
    official_npm = [
        e
        for e in evidence
        if e.valuation_metric == "NPM"
        and e.source_url == NPM_PAGE_URL
        and e.source == NPM_API_URL
        and e.valuation_status == "observed"
        and e.claim_kind == "fact"
        and e.event_at is not None
        and e.published_at is not None
        and e.confidence >= 0.75
        and not e.synthetic
        and e.evidence_id not in result.invalid_settlement_evidence
    ]
    if official_npm:
        latest_date = max(e.event_at.date() for e in official_npm)
        latest = [e for e in official_npm if e.event_at.date() == latest_date]
        # Conflicting values for the same observation date remain disputed.
        if len({e.valuation_usd_billion for e in latest}) == 1:
            anchor = max(latest, key=lambda e: e.retrieved_at)
            disputed.discard(anchor.evidence_id)
            result.accepted_evidence.append(anchor.evidence_id)
    result.disputed_evidence = sorted(disputed)
    result.accepted_evidence = sorted(set(result.accepted_evidence) - disputed)
    directions = {e.impact_direction for e in evidence}
    if "negative" not in directions:
        result.potential_biases.append("未发现负面证据，存在单向检索偏差")
        result.recommended_followup_queries.append(
            "OpenAI losses competition regulation downside risks"
        )
    if not any(e.category == "profitability" for e in evidence):
        result.missing_information.append("缺少可靠盈利与算力成本信息")
    result.potential_biases.append("因果路径是模型假设；来源可信度不等于事件概率")
    if any(e.stale for e in evidence):
        result.potential_biases.append(
            "历史证据保留过时标记；数值模型单独传播锚点年龄与代理不确定性。"
        )
    return result
