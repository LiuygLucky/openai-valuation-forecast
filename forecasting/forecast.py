from core.config import MarketRules
from core.schemas import CognitiveState, Forecast


def generate_forecast(state: CognitiveState, rules: MarketRules) -> Forecast:
    b = state.belief_state
    assumptions = [
        f"基准估值 {b['baseline_valuation']} USD billion；来源 {b['baseline_source']}",
        f"先验参数：{b['prior_assumptions']}",
        f"事件情景：{b['scenario_assumptions']}",
        "目标是终点估值区间，不是截止日期前触及阈值的路径事件。",
    ]
    return Forecast(
        question=state.question,
        as_of=state.as_of,
        target_date=state.target_date,
        valuation_metric=rules.valuation_metric,
        market_rules_source=rules.market_rules_source,
        mode=state.mode,
        probabilities=b["posterior_distribution"],
        baseline_probabilities=b["baseline_distribution"],
        median_valuation=b["median"],
        confidence_interval_90=b["interval_90"],
        key_evidence_ids=state.critique.accepted_evidence if state.critique else state.evidence_ids,
        main_assumptions=assumptions,
        limitations=b["uncertainty_notes"] + state.warnings,
    )
