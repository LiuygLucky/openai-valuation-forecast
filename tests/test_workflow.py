from datetime import datetime, timezone

import pytest

from core.config import load_config
from core.controller import run_forecast
from evaluation.history import compare_runs
from memory.evidence_store import EvidenceStore


def test_complete_workflow(tmp_path):
    settings, rules = load_config()
    settings.database = str(tmp_path / "evidence.sqlite")
    settings.output_dir = str(tmp_path / "reports")
    as_of = datetime(2026, 11, 2, tzinfo=timezone.utc)
    state = run_forecast("OpenAI 2026-12-31 valuation", settings, rules, demo=True, as_of=as_of)
    assert state.status == "completed"
    assert state.iteration_count == settings.max_iterations
    assert state.trace[-1] == "SaveRun"
    assert state.information_gaps and state.hypotheses and state.forecast
    assert sum(p.probability for p in state.forecast.probabilities) == pytest.approx(1)
    assert state.usage["llm_calls"] == 0
    saved = EvidenceStore(settings.database).runs("demo")[0]
    assert saved == state
    assert any(p["log_shift"] != 0 for p in state.belief_state["event_adjustments"])
    assert (
        next(
            p
            for p in state.belief_state["event_adjustments"]
            if p["event_key"] == "synthetic-financing"
        )["log_shift"]
        == 0
    )
    assert not compare_runs(state, saved)["new_evidence_ids"]
    assert state.coverage["passed"]
    from pathlib import Path

    from scripts.verify_run import verify

    assert verify(Path(state.report_path).parent / "state.json")["passed"]
    changed = state.model_copy(deep=True)
    changed.forecast.probabilities[0].probability += 0.01
    changed.forecast.probabilities[1].probability -= 0.01
    for row in compare_runs(state, changed)["probability_changes"]:
        assert row["delta_percentage_points"] == pytest.approx(
            row["baseline_delta_pp"] + row["event_component_delta_pp"]
        )


def test_iteration_limit_one(tmp_path):
    settings, rules = load_config()
    settings.database = str(tmp_path / "evidence.sqlite")
    settings.output_dir = str(tmp_path / "reports")
    settings.max_iterations = 1
    state = run_forecast(
        "OpenAI valuation",
        settings,
        rules,
        demo=True,
        as_of=datetime(2026, 11, 2, tzinfo=timezone.utc),
    )
    assert state.iteration_count == 1


def test_historical_live_refused():
    settings, rules = load_config()
    with pytest.raises(ValueError, match="historical"):
        run_forecast(
            "OpenAI valuation", settings, rules, as_of=datetime(2025, 1, 1, tzinfo=timezone.utc)
        )
