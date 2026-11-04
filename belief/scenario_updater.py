import re

import numpy as np

from belief.baseline import MissingAnchor, select_anchor
from belief.distribution import interval_probabilities, simulate
from belief.settlement import confirms_invalid_private_metric
from core.config import MarketRules, Settings
from core.schemas import CognitiveState
from reasoning.critic import event_groups


def update_belief(state: CognitiveState, settings: Settings, rules: MarketRules) -> dict:
    invalid = set(state.critique.invalid_settlement_evidence) if state.critique else set()
    if any(
        e.evidence_id in invalid
        and confirms_invalid_private_metric(e)
        and e.confidence >= 0.75
        and e.epistemic_status in ("Verified Fact", "Reported Claim")
        for e in state.retrieved_evidence
    ):
        raise MissingAnchor(
            "Evidence indicates IPO/invalid private settlement metric; revise settlement definition"
        )
    accepted = set(state.critique.accepted_evidence) if state.critique else set()
    updated_model = state.forecast is None or state.forecast.model_version not in (
        "v1.0", "v1.1", "v1.2", "v1.3"
    )
    usable = [e for e in state.retrieved_evidence if e.evidence_id in accepted]
    anchor = select_anchor(usable, rules, state.as_of, state.mode, settings.max_anchor_age_days)
    origin = anchor.event_at or anchor.published_at
    age_years = (state.as_of - origin).total_seconds() / (365.25 * 86400)
    unknown_date_sigma = settings.unknown_event_date_log_sigma if anchor.event_at is None else 0.0
    extra_sigma = float(
        np.sqrt(settings.anchor_age_log_sigma**2 * age_years + unknown_date_sigma**2)
    )
    adjustments = []
    residual_risks = []
    for group in event_groups(usable):
        ids = {e.evidence_id for e in group}
        evidence = group[0]
        hs = [h for h in state.hypotheses if ids.intersection(h.evidence_ids)]
        directions = {h.direction for h in hs}
        delta, explanation = 0.0, "No supported directional mechanism"
        event_time = evidence.event_at or evidence.published_at
        future_forecast = updated_model and (
            evidence.claim_kind == "forecast"
            and evidence.category not in ("valuation", "financing")
            and str(state.target_date.year) in evidence.support_quote
            and len(hs) > 0
            and directions in ({"positive"}, {"negative"})
            and evidence.published_at <= anchor.published_at
            and evidence.published_at <= state.as_of
            and not re.search(r"\b(?:completed|realized|already occurred)\b", evidence.claim, re.I)
        )
        if future_forecast:
            # Known forecasts are in the mark. Their future realization can still
            # differ from what the mark implies; model a zero-centered residual.
            amplitude = settings.event_log_shift
            residual_risks.append(
                {"event_key": evidence.event_key, "evidence_ids": sorted(ids),
                 "log_amplitude": amplitude, "direction": next(iter(directions))}
            )
            explanation = "Known forward forecast: zero-centered future realization risk"
        elif (
            event_time <= origin
            or evidence.published_at <= anchor.published_at
            or anchor.evidence_id in ids
        ):
            explanation = "Event/disclosure at or before anchor: assumed embedded in baseline"
        elif evidence.claim_kind in ("rumor", "opinion", "unknown") and not evidence.synthetic:
            explanation = "Unverified event nature: excluded from numerical adjustment"
        elif evidence.category in ("valuation", "financing"):
            explanation = "Valuation/financing already represented by anchor; no second adjustment"
        elif "positive" in directions and "negative" in directions:
            explanation = "Conflicting causal directions; zero net shift"
        elif hs:
            direction = 1 if directions == {"positive"} else -1 if directions == {"negative"} else 0
            priced_in = {"likely": 0.0, "possible": 0.5, "unlikely": 1.0, "unknown": 0.25}
            discount = min(priced_in[h.priced_in] for h in hs)
            recency = np.exp(-max(0, (state.as_of - evidence.published_at).days) / 365.25)
            delta = float(direction * settings.event_log_shift * discount * recency)
            explanation = "Explicit heuristic log shift, discounted for possible prior pricing; NOT calibrated"
        adjustments.append(
            {
                "event_key": evidence.event_key,
                "evidence_ids": sorted(ids),
                "log_shift": delta,
                "reason": explanation,
            }
        )
    shift = float(
        np.clip(
            sum(a["log_shift"] for a in adjustments),
            -settings.max_total_log_shift,
            settings.max_total_log_shift,
        )
    )
    years = (state.target_date - origin).total_seconds() / (365.25 * 86400)
    baseline, _ = simulate(
        anchor.valuation_usd_billion,
        years,
        settings,
        shift=shift,
        proxy=rules.provider == "financing_proxy",
        extra_log_sigma=extra_sigma,
    )
    # Uncalibrated discrete event-effect scenarios, with weights declared in the audit trail.
    rng = np.random.default_rng(settings.seed + 1)
    factors = rng.choice([0.0, 1.0, 2.0], settings.samples, p=[0.25, 0.5, 0.25])
    residual_shift = np.zeros(settings.samples)
    if updated_model:
        residual_rng = np.random.default_rng(settings.seed + 2)
        for risk in residual_risks:
            residual_shift += risk["log_amplitude"] * residual_rng.choice(
                [-1.0, 0.0, 1.0], settings.samples, p=[0.25, 0.5, 0.25]
            )
    posterior = baseline * np.exp(
        np.clip(shift * factors + residual_shift,
                -settings.max_total_log_shift, settings.max_total_log_shift)
    )
    counts, edges = np.histogram(posterior, bins=60)
    scenario_assumptions = {
        "effect_factors": [0, 1, 2],
        "weights": [0.25, 0.5, 0.25],
        "net_log_shift": shift,
        "max_total_log_shift": settings.max_total_log_shift,
        "interpretation": "Heuristic event effect absent / central / doubled, not estimated probabilities",
    }
    if updated_model:
        scenario_assumptions.update({
            "residual_risk_outcomes": [-1, 0, 1],
            "residual_risk_weights": [0.25, 0.5, 0.25],
            "interpretation": "Post-anchor event shifts plus zero-centered realization risk for sourced forward forecasts; heuristic, not calibrated",
        })
    result = {
        "prior_assumptions": {
            "annual_log_volatility": settings.annual_log_volatility,
            "annual_log_drift": settings.annual_log_drift,
            "years": years,
            "anchor_origin": origin.isoformat(),
            "anchor_time_basis": anchor.event_time_basis
            if anchor.event_at
            else "publication_proxy",
            "anchor_age_years": age_years,
            "extra_log_sigma": extra_sigma,
            "anchor_age_log_sigma_per_sqrt_year": settings.anchor_age_log_sigma,
            "unknown_event_date_log_sigma": unknown_date_sigma,
            "proxy_extra_log_sigma": settings.proxy_extra_log_sigma
            if rules.provider == "financing_proxy"
            else 0,
            "seed": settings.seed,
            "samples": settings.samples,
            "formula": "V_T = anchor * exp(drift*T_anchor_to_target + sqrt(vol^2*T_anchor_to_target + proxy_sigma^2 + age_risk_sigma^2*age_years + unknown_date_sigma^2)*Z + clipped(event_shift*scenario_factor))",
        },
        "baseline_valuation": anchor.valuation_usd_billion,
        "baseline_source": anchor.source_url,
        "baseline_evidence_id": anchor.evidence_id,
        "baseline_published_at": anchor.published_at.isoformat(),
        "event_adjustments": adjustments,
        "scenario_assumptions": scenario_assumptions,
        "posterior_distribution": [
            p.model_dump() for p in interval_probabilities(posterior, rules.intervals)
        ],
        "baseline_distribution": [
            p.model_dump() for p in interval_probabilities(baseline, rules.intervals)
        ],
        "median": float(np.median(posterior)),
        "interval_90": np.quantile(posterior, [0.05, 0.95]).tolist(),
        "histogram": {"counts": counts.tolist(), "edges": edges.tolist()},
        "uncertainty_notes": [
            *(
                [
                    "部分指标失效标记缺乏已完成事实的原文支持；IPO 筹备/意向仅作为结算风险，未当作已经上市。"
                ]
                if any(
                    e.evidence_id in invalid and not confirms_invalid_private_metric(e)
                    for e in state.retrieved_evidence
                )
                else []
            ),
            f"锚点距信息截止 {age_years * 365.25:.1f} 天；从锚点时点传播，不当作当前报价。额外陈旧性模型误差与过程波动分别记录。",
            "事件日期未知时使用公告时间代理，并增加日期不明误差；该时点不声称为确切成交时间。",
            "启发式预测；波动率、事件幅度和情景权重未经历史数据校准。",
            "可信度仅用于证据筛选，不被解释成事件发生概率。",
            "融资估值代理与私募二级市场结算价格不同。"
            if rules.provider == "financing_proxy"
            else "需遵守指定报价商的数据口径。",
            "90% 区间为模型分布区间，不是经过验证的覆盖率承诺。",
        ],
    }
    if updated_model:
        result["future_realization_risks"] = residual_risks
    return result
