"""Recompute a completed run locally after a numerical fix; archive its prior report."""

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from belief.scenario_updater import update_belief
from core.checkpoint import write_checkpoint
from core.config import ROOT, MarketRules, Settings
from core.schemas import CognitiveState, utcnow
from forecasting.forecast import generate_forecast
from forecasting.report import write_report
from memory.evidence_store import EvidenceStore
from reasoning.coverage import assess_coverage
from reasoning.critic import event_groups


def recompute(path):
    state = CognitiveState.model_validate_json(Path(path).read_text(encoding="utf-8"))
    if state.status != "completed":
        raise ValueError("Only a completed research snapshot can be recomputed")
    settings = Settings.model_validate(state.belief_state["settings_snapshot"])
    rules = MarketRules.model_validate(state.belief_state["rules_snapshot"])
    archive = ROOT / "reports" / "revisions" / state.run_id / utcnow().strftime("%Y%m%dT%H%M%S%f")
    shutil.copytree(Path(state.report_path).parent, archive)
    accepted = set(state.critique.accepted_evidence)
    duplicate_ids = {
        e.evidence_id
        for group in event_groups(
            [e for e in state.retrieved_evidence if e.evidence_id in accepted]
        )
        for e in group[1:]
    }
    state.critique.accepted_evidence = sorted(accepted - duplicate_ids)
    state.critique.disputed_evidence = sorted(set(state.critique.disputed_evidence) | duplicate_ids)
    state.coverage = assess_coverage(state, settings)
    if not state.coverage["passed"]:
        raise ValueError("Recomputed evidence no longer satisfies coverage")
    state.belief_state = update_belief(state, settings, rules)
    state.belief_state["settings_snapshot"] = settings.model_dump()
    state.belief_state["rules_snapshot"] = rules.model_dump(mode="json")
    state.warnings.append(
        f"本地数值修复重算，未新增网络调用，信息截止不变；原报告保存在 {archive.relative_to(ROOT).as_posix()}。"
    )
    state.forecast = generate_forecast(state, rules)
    state.trace.extend(["LocalNumericalRecompute", "SaveRun"])
    EvidenceStore(ROOT / settings.database).snapshot(state, "LocalNumericalRecompute")
    write_checkpoint(
        ROOT / settings.output_dir / f"{state.run_id}.state.json", state.model_dump_json(indent=2)
    )
    write_report(state, rules, ROOT / settings.output_dir)
    return state


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state", type=Path)
    state = recompute(parser.parse_args().state)
    print(state.report_path)
    print(
        "No new API calls; probability sum:",
        sum(p.probability for p in state.forecast.probabilities),
    )
