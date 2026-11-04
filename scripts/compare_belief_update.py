"""Offline counterfactual: apply the current updater to a saved run without changing it."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from belief.scenario_updater import update_belief
from core.config import MarketRules, Settings
from core.schemas import CognitiveState


def compare(path: Path) -> dict:
    saved = CognitiveState.model_validate_json(path.read_text(encoding="utf-8"))
    if saved.status != "completed" or saved.forecast is None:
        raise ValueError("A completed archived forecast is required")
    settings = Settings.model_validate(saved.belief_state["settings_snapshot"])
    rules = MarketRules.model_validate(saved.belief_state["rules_snapshot"])
    current = saved.model_copy(deep=True)
    current.forecast = None  # Select the current algorithm; do not mutate the archived run.
    recalculated = update_belief(current, settings, rules)
    old = saved.forecast.probabilities
    new = recalculated["posterior_distribution"]
    return {
        "label": "offline_counterfactual_not_a_new_live_forecast",
        "source_run_id": saved.run_id,
        "source_as_of": saved.as_of.isoformat(),
        "old_model_version": saved.forecast.model_version,
        "new_model_version": "v1.4",
        "same_saved_evidence_and_parameters": True,
        "new_network_calls": 0,
        "future_realization_risks": recalculated["future_realization_risks"],
        "intervals": [
            {
                "interval": before.interval,
                "old_probability": before.probability,
                "counterfactual_probability": after["probability"],
                "difference_percentage_points": round(
                    (after["probability"] - before.probability) * 100, 6
                ),
            }
            for before, after in zip(old, new, strict=True)
        ],
        "old_median_usd_billion": saved.forecast.median_valuation,
        "counterfactual_median_usd_billion": recalculated["median"],
        "warning": "Scenario magnitudes and weights are uncalibrated; this is an algorithm comparison, not evidence of predictive accuracy.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = compare(args.state)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)
