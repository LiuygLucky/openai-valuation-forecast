"""Rebuild the explicitly synthetic, fixed-date deliverable report."""

import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import ROOT, load_config
from core.controller import run_forecast

settings, rules = load_config()
settings.database = "data/deliverable_demo.sqlite"
settings.output_dir = "reports/demo_runs"
state = run_forecast(
    "预测 OpenAI 在 2026 年 12 月 31 日的私募估值区间概率。",
    settings,
    rules,
    demo=True,
    as_of=datetime(2026, 11, 2, 6, 30, tzinfo=timezone.utc),
)
destination = ROOT / "reports/demo"
shutil.copytree(Path(state.report_path).parent, destination, dirs_exist_ok=True)
(destination / "state.json").write_text(state.model_dump_json(indent=2), encoding="utf-8")
print(f"DEMO / SYNTHETIC report: {destination / 'report.md'}")
print(f"Probability sum: {sum(p.probability for p in state.forecast.probabilities):.10f}")
print(f"Iterations: {state.iteration_count}; API calls: {state.usage['llm_calls']}")
