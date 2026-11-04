"""Command-line entry point; --demo explicitly selects synthetic data."""

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path

from belief.baseline import select_anchor
from belief.distribution import interval_probabilities, simulate
from core.budget import Budget
from core.config import ROOT, load_config
from core.llm import JsonLLM
from core.schemas import utcnow
from core.task_parser import parse_task
from perception.demo import DemoLLM, DemoSearch
from perception.evidence_extractor import extract
from perception.search_client import TavilySearch, parse_date


def re_timezone(value: str) -> bool:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def minimal(args):
    settings, rules = load_config(args.settings, args.rules)
    as_of = parse_date(args.as_of) if args.as_of else utcnow()
    if not args.demo and args.as_of:
        raise ValueError("Historical live web search is not a valid backtest")
    if as_of is None:
        raise ValueError("Invalid as_of timestamp")
    rules, task_spec = parse_task(args.question, rules, as_of)
    budget = Budget(settings)
    search = DemoSearch(as_of, rules.provider) if args.demo else TavilySearch(budget)
    llm = DemoLLM(rules.provider) if args.demo else JsonLLM(budget)
    results = search.search("OpenAI latest funding equity valuation")
    if not args.as_of:
        as_of = utcnow()
    evidence = extract(results, llm, as_of, settings.stale_days)
    anchor = select_anchor(
        evidence, rules, as_of, "demo" if args.demo else "live", settings.max_anchor_age_days
    )
    origin = anchor.event_at or anchor.published_at
    age_years = (as_of - origin).total_seconds() / (365.25 * 86400)
    extra_sigma = math.sqrt(
        settings.anchor_age_log_sigma**2 * age_years
        + (settings.unknown_event_date_log_sigma**2 if anchor.event_at is None else 0)
    )
    _, samples = simulate(
        anchor.valuation_usd_billion,
        (rules.target_date - origin).total_seconds() / (365.25 * 86400),
        settings,
        proxy=rules.provider == "financing_proxy",
        extra_log_sigma=extra_sigma,
    )
    result = {
        "mode": "DEMO / SYNTHETIC" if args.demo else "LIVE / HEURISTIC",
        "as_of": as_of.isoformat(),
        "target_date": rules.target_date.isoformat(),
        "baseline_source": anchor.source_url,
        "anchor_origin": origin.isoformat(),
        "extra_log_sigma": extra_sigma,
        "task_spec": task_spec,
        "scope": "Baseline smoke check only; full research acceptance requires the default workflow",
        "unit": rules.unit,
        "probabilities": [p.model_dump() for p in interval_probabilities(samples, rules.intervals)],
        "usage": budget.snapshot(),
    }
    path = ROOT / "reports" / ("minimal_demo.json" if args.demo else "minimal_live.json")
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--run-id", help="Run identifier assigned by the dashboard worker")
    parser.add_argument(
        "--resume-from",
        choices=["ProcessEvidence", "Critique"],
        help="Explicitly retry saved evidence processing or review; keeps cumulative budget",
    )
    parser.add_argument(
        "--resume", help="Resume a saved incomplete run_id; preserves cumulative budget"
    )
    parser.add_argument("--minimal", action="store_true", help="Milestone 1 smoke workflow")
    parser.add_argument("--settings", type=Path)
    parser.add_argument("--rules", type=Path)
    parser.add_argument(
        "--as-of", help="Timezone-aware ISO timestamp; historical live search is refused"
    )
    parser.add_argument(
        "--question", default="预测 OpenAI 在 2026 年 12 月 31 日的私募估值区间概率。"
    )
    args = parser.parse_args()
    try:
        if args.as_of and (parse_date(args.as_of) is None or not re_timezone(args.as_of)):
            raise ValueError("--as-of requires a valid timezone-aware ISO timestamp")
        if args.minimal:
            minimal(args)
        else:
            from core.controller import run_forecast

            settings, rules = load_config(args.settings, args.rules)
            state = run_forecast(
                args.question,
                settings,
                rules,
                demo=args.demo,
                as_of=parse_date(args.as_of) if args.as_of else None,
                resume_id=args.resume,
                resume_from=args.resume_from,
                run_id=args.run_id,
                on_step=lambda name, state: print(
                    f"[{state.run_id[:8]}] {name} / round {state.iteration_count}",
                    file=sys.stderr,
                    flush=True,
                ),
            )
            print(state.forecast.model_dump_json(indent=2))
            print(f"Report: {state.report_path}")
    except (ValueError, RuntimeError, OSError) as exc:
        parser.exit(1, f"Forecast failed: {exc}\n")


if __name__ == "__main__":
    main()
