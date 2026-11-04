"""Audit a saved run and exactly replay its numerical model without network calls."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from belief.scenario_updater import update_belief
from core.config import MarketRules, Settings
from core.schemas import CognitiveState, utcnow
from perception.dates import normalized_quote
from reasoning.coverage import assess_coverage


def verify(path: Path) -> dict:
    state = CognitiveState.model_validate_json(path.read_text(encoding="utf-8"))
    settings = Settings.model_validate(state.belief_state["settings_snapshot"])
    rules = MarketRules.model_validate(state.belief_state["rules_snapshot"])
    replay = update_belief(state, settings, rules)
    folder = Path(state.report_path).parent
    accepted = set(state.critique.accepted_evidence)
    evidence = [e for e in state.retrieved_evidence if e.evidence_id in accepted]
    checks = {
        "budget_limits": state.usage.get("estimated_cost_usd", 0) <= settings.budget_usd
        and state.usage.get("reserved_tokens", 0) <= settings.max_tokens
        and state.usage.get("llm_calls", 0) <= settings.max_llm_calls
        and state.usage.get("search_calls", 0) <= settings.max_search_calls,
        "no_future_occurred_facts": all(
            e.claim_kind != "fact" or e.event_at is None or e.event_at <= state.as_of
            for e in evidence
        ),
        "completed": state.status == "completed" and state.trace[-1] == "SaveRun",
        "coverage": assess_coverage(state, settings)["passed"],
        "mode_isolation": all(
            e.synthetic == (state.mode == "demo") for e in state.retrieved_evidence
        ),
        "source_grounding": all(
            e.synthetic or normalized_quote(e.support_quote, e.raw_content) for e in evidence
        ),
        "time_isolation": all(
            e.retrieved_at <= state.as_of and e.published_at and e.published_at <= state.as_of
            for e in evidence
        ),
        "probability_sum": abs(sum(p.probability for p in state.forecast.probabilities) - 1) < 1e-8,
        "exact_numeric_replay": all(state.belief_state[k] == v for k, v in replay.items()),
        "complete_artifacts": all(
            (folder / name).is_file()
            for name in (
                "report.md",
                "state.json",
                "forecast.json",
                "probabilities.svg",
                "probabilities.html",
                "terminal_distribution.html",
            )
        ),
        "archive_state_matches": CognitiveState.model_validate_json(
            (folder / "state.json").read_text(encoding="utf-8")
        )
        == state,
    }
    result = {
        "run_id": state.run_id,
        "mode": state.mode,
        "verified_at": utcnow().isoformat(),
        "network_calls": 0,
        "checks": checks,
        "passed": all(checks.values()),
    }
    (folder / "verification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state", type=Path)
    result = verify(parser.parse_args().state)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
