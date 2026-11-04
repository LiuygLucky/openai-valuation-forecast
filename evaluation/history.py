from core.schemas import CognitiveState


def compare_runs(older: CognitiveState, newer: CognitiveState) -> dict:
    if older.forecast is None or newer.forecast is None:
        raise ValueError("Only completed forecasts can be compared")
    a, b = older.forecast, newer.forecast
    if (a.mode, a.target_date, a.valuation_metric, a.market_rules_source, a.unit) != (
        b.mode,
        b.target_date,
        b.valuation_metric,
        b.market_rules_source,
        b.unit,
    ):
        raise ValueError("Incompatible modes, targets, units or settlement definitions")
    if [p.interval for p in a.probabilities] != [p.interval for p in b.probabilities]:
        raise ValueError("Incompatible intervals; re-bin from raw samples before comparison")
    ar = older.belief_state.get("rules_snapshot", {})
    br = newer.belief_state.get("rules_snapshot", {})
    if ar != br:
        raise ValueError("Incompatible settlement rules or interval boundaries")
    changes = [
        {
            "interval": x.interval,
            "old": x.probability,
            "new": y.probability,
            "delta_percentage_points": 100 * (y.probability - x.probability),
            "baseline_delta_pp": 100 * (yb.probability - xb.probability),
            "event_component_delta_pp": 100
            * ((y.probability - yb.probability) - (x.probability - xb.probability)),
        }
        for x, y, xb, yb in zip(
            a.probabilities,
            b.probabilities,
            a.baseline_probabilities,
            b.baseline_probabilities,
            strict=True,
        )
    ]
    old_events = {r["event_key"]: r for r in older.belief_state["event_adjustments"]}
    new_events = {r["event_key"]: r for r in newer.belief_state["event_adjustments"]}
    evidence = {e.evidence_id: e for e in older.retrieved_evidence + newer.retrieved_evidence}
    explanations = []
    top = max(changes, key=lambda r: abs(r["delta_percentage_points"]))
    explanations.append(
        f"变化最大区间 {top['interval']}：{top['delta_percentage_points']:+.2f} 个百分点；"
        f"其中基准分布差 {top['baseline_delta_pp']:+.2f}，事件调整分量差 {top['event_component_delta_pp']:+.2f}。此为算术分解，不是因果效应估计。"
    )
    if older.belief_state["baseline_valuation"] != newer.belief_state["baseline_valuation"]:
        explanations.append(
            f"估值锚点从 {older.belief_state['baseline_valuation']} 变为 {newer.belief_state['baseline_valuation']} USD billion；"
            f"新来源：{newer.belief_state['baseline_source']}"
        )
    if older.belief_state["prior_assumptions"] != newer.belief_state["prior_assumptions"]:
        explanations.append(
            "先验参数或锚点年龄发生变化；请区分时间推移带来的不确定性变化与新证据影响。"
        )
    event_details = []
    for key in sorted(old_events.keys() | new_events.keys()):
        old, new = old_events.get(key, {}), new_events.get(key, {})
        delta = new.get("log_shift", 0) - old.get("log_shift", 0)
        if delta or bool(old) != bool(new):
            ids = sorted(set(old.get("evidence_ids", []) + new.get("evidence_ids", [])))
            sources = [
                {"evidence_id": i, "claim": evidence[i].claim, "url": evidence[i].source_url}
                for i in ids
                if i in evidence
            ]
            event_details.append({"event_key": key, "log_shift_delta": delta, "sources": sources})
            explanations.append(
                f"事件 {key} 的对数调整变化 {delta:+.5f}；来源 "
                + ", ".join(s["url"] for s in sources)
            )
    if a.model_version != b.model_version:
        explanations.append(
            f"模型版本变更：{a.model_version} → {b.model_version}，不能将全部差异归为新闻影响。"
        )
    return {
        "older_run_id": older.run_id,
        "newer_run_id": newer.run_id,
        "explanations": explanations,
        "event_details": event_details,
        "probability_changes": [row for row in changes],
        "new_evidence_ids": sorted(set(newer.evidence_ids) - set(older.evidence_ids)),
        "removed_evidence_ids": sorted(set(older.evidence_ids) - set(newer.evidence_ids)),
        "baseline_changed": older.belief_state["baseline_valuation"]
        != newer.belief_state["baseline_valuation"],
        "prior_changes": {
            "old": older.belief_state["prior_assumptions"],
            "new": newer.belief_state["prior_assumptions"],
        },
        "event_changes": {
            "old": older.belief_state["event_adjustments"],
            "new": newer.belief_state["event_adjustments"],
        },
        "note": "描述性差异，不是对概率变化的严格因果归因；时间跨度变化也会改变分布。",
    }
