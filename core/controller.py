"""Bounded LangGraph research workflow with durable per-node state snapshots."""

import logging
import re
from datetime import datetime
from typing import Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from belief.baseline import MissingAnchor, select_anchor
from belief.scenario_updater import update_belief
from core.budget import Budget, BudgetExceeded
from core.checkpoint import write_checkpoint
from core.config import ROOT, MarketRules, Settings
from core.llm import JsonLLM
from core.schemas import CognitiveState, utcnow
from core.task_parser import parse_task
from evaluation.history import compare_runs
from forecasting.forecast import generate_forecast
from forecasting.report import write_report
from memory.evidence_store import EvidenceStore
from memory.vector_store import VectorMemory
from perception.demo import DemoLLM, DemoSearch
from perception.evidence_extractor import EXTRACTION_VERSION, extract, result_id, source_quality
from perception.npm_official import NPM_API_URL, fetch_npm_snapshot, parse_npm_snapshot
from perception.research_planner import (
    diverse_queries,
    document_priority,
    document_topic,
    plan_research,
)
from perception.search_client import SearchClient, SearchError, TavilySearch
from reasoning.causal_reasoner import reason
from reasoning.coverage import InsufficientEvidence, assess_coverage, coverage_queries
from reasoning.critic import critique
from reasoning.gap_detector import needs_followup

logger = logging.getLogger(__name__)


class GraphState(TypedDict):
    cognitive: dict


def validate_question(question: str, rules: MarketRules) -> None:
    if "openai" not in question.lower():
        raise ValueError("V1 supports OpenAI terminal private equity valuation only")
    if not any(word in question.lower() for word in ("估值", "valuation", "equity value")):
        raise ValueError("V1 requires an explicit valuation question")
    for provider in ("NPM", "Forge"):
        if provider.lower() in question.lower() and rules.provider != provider:
            raise ValueError(
                "Question metric differs from configured provider; update market_rules.yaml"
            )
    if any(
        word in question.lower()
        for word in ("最高", "曾经", "触及", "ever reach", "maximum", "hit before")
    ):
        raise ValueError("Path/barrier events are not terminal interval events")
    dates = re.findall(r"(20\d{2})[-年/ ]+\s*(\d{1,2})[-月/ ]+\s*(\d{1,2})", question)
    if dates and any(
        tuple(map(int, d))
        != (rules.target_date.year, rules.target_date.month, rules.target_date.day)
        for d in dates
    ):
        raise ValueError(
            "Question date differs from configured target date; update market_rules.yaml"
        )


def run_forecast(
    question: str,
    settings: Settings,
    rules: MarketRules,
    *,
    demo: bool = False,
    as_of: datetime | None = None,
    on_step: Callable[[str, CognitiveState], None] | None = None,
    search_client: SearchClient | None = None,
    llm_client: JsonLLM | DemoLLM | None = None,
    resume_id: str | None = None,
    resume_from: str | None = None,
    run_id: str | None = None,
) -> CognitiveState:
    mode = "demo" if demo else "live"
    if not demo and as_of is not None:
        raise ValueError(
            "Live web search cannot establish historical availability. Use current live mode; historical as_of is demo-only."
        )
    cutoff = as_of or utcnow()
    state = CognitiveState(
        question=question,
        as_of=cutoff,
        target_date=rules.target_date,
        mode=mode,
        **({"run_id": run_id} if run_id else {}),
    )
    store = EvidenceStore(ROOT / settings.database)
    budget = Budget(settings)
    latest = state
    output = ROOT / settings.output_dir
    output.mkdir(parents=True, exist_ok=True)
    resume_node = None
    if resume_from and (not resume_id or resume_from not in ("ProcessEvidence", "Critique")):
        raise ValueError("Explicit retry requires --resume and a supported node")
    if resume_id:
        previous = next((run for run in store.runs(mode) if run.run_id == resume_id), None)
        if previous is None:
            raise ValueError("Resume run not found in the selected mode")
        if previous.status == "completed":
            return previous
        state = previous
        resume_node = next(
            (n for n in reversed(state.trace) if n not in ("Failed", "Resumed")), None
        )
        state.status = "running"
        state.trace.append("Resumed")
        state.warnings.append(
            "从持久化节点续跑；沿用原始证据和预算累计，计算使用本次明确保存的配置。"
        )
        if resume_from == "ProcessEvidence":
            state.warnings.append(
                "显式重试 ProcessEvidence：复用保存的真实搜索结果重新抽取、推理和审查；不重置预算。"
            )
        elif resume_from == "Critique":
            state.warnings.append(
                "显式重试 Critique：复用保存的证据与假设重新审查；不重置预算。"
            )
        for key, value in state.usage.items():
            if key != "settings":
                setattr(budget, key, value)
        rules, state.task_spec = parse_task(state.question, rules, state.as_of)
        cutoff = state.as_of
        latest = state
    try:
        search = search_client or (
            DemoSearch(cutoff, rules.provider) if demo else TavilySearch(budget)
        )
        llm = llm_client or (DemoLLM(rules.provider) if demo else JsonLLM(budget))
        vectors = VectorMemory(
            "hashing-char-1024" if demo else settings.embedding_model,
            budget=budget,
            cache_path=ROOT / settings.embedding_cache,
        )

        def parse(s):
            nonlocal rules
            rules, s.task_spec = parse_task(s.question, rules, s.as_of)
            s.target_date = rules.target_date
            if s.target_date <= s.as_of:
                raise ValueError("Target date must follow information cutoff")
            s.warnings.extend(
                [
                    "采用自主定义的终点估值区间；Polymarket 仅为题目来源。",
                    "非校准启发式概率；不得解释成经过回测验证的后验。",
                ]
            )
            if demo:
                s.warnings.append("DEMO / SYNTHETIC：所有输入是合成测试数据；无真实 API 调用。")
            else:
                s.warnings.append(
                    "实时研究的信息截止时间将在每轮采集结束时更新；不能作为合格历史回测。"
                )

        def plan(s):
            s.retrieved_evidence = [
                e for e in store.query(s.as_of, mode) if e.extraction_version == EXTRACTION_VERSION
            ]
            s.research_plan = plan_research(llm, s.question, rules, s.as_of, s.retrieved_evidence)

        def search_node(s):
            s.iteration_count += 1
            queries = (
                diverse_queries(s.research_plan)
                if not s.critique
                else s.critique.recommended_followup_queries
            )
            previous = {q["query"] for q in s.search_history}
            pending = list(dict.fromkeys(q for q in queries if q not in previous))[
                : settings.queries_per_round
            ]
            results = []
            if rules.provider == "NPM" and not demo:
                try:
                    budget.reserve("search")
                    official = fetch_npm_snapshot()
                    results.append(official)
                    s.search_history.append(
                        {
                            "query": official.query,
                            "iteration": s.iteration_count,
                            "count": 1,
                            "status": "ok",
                            "time": official.retrieved_at.isoformat(),
                            "kind": "official_npm_snapshot",
                        }
                    )
                except (SearchError, BudgetExceeded) as exc:
                    s.warnings.append(str(exc))
                    s.search_history.append(
                        {
                            "query": "Official NPM OpenAI valuation feed",
                            "iteration": s.iteration_count,
                            "count": 0,
                            "status": "failed",
                            "error": str(exc),
                        }
                    )
            for q in pending:
                try:
                    history_start = len(getattr(search, "request_history", []))
                    fetched = search.search(q)
                    if any(r.synthetic != demo for r in fetched):
                        raise ValueError(
                            "Data mode mismatch: refusing synthetic/live contamination"
                        )
                    results.extend(fetched)
                    s.search_history.append(
                        {
                            "query": q,
                            "iteration": s.iteration_count,
                            "count": len(fetched),
                            "status": "ok",
                            "time": utcnow().isoformat(),
                        }
                    )
                    s.search_history.extend(
                        record
                        | {
                            "iteration": s.iteration_count,
                            "status": "ok",
                            "kind": "publication_metadata",
                        }
                        for record in getattr(search, "request_history", [])[history_start:]
                        if record["query"] != q
                    )
                except (SearchError, BudgetExceeded) as exc:
                    s.search_history.append(
                        {
                            "query": q,
                            "iteration": s.iteration_count,
                            "count": 0,
                            "status": "failed",
                            "error": str(exc),
                        }
                    )
                    s.warnings.append(str(exc))
                    if isinstance(exc, BudgetExceeded):
                        break
            s.search_results = results
            if not demo:
                s.as_of = utcnow()
                s.task_spec["as_of"] = s.as_of.isoformat()
            if not results and not s.evidence_ids:
                raise SearchError("No external evidence obtained; refusing an unsupported forecast")

        def process(s):
            npm_docs = [r for r in s.search_results if r.url == NPM_API_URL]
            npm_evidence = [parse_npm_snapshot(r) for r in npm_docs]
            if npm_evidence:
                store.save_evidence(npm_evidence, mode)
                s.processing_history.extend(
                    {
                        "document_id": result_id(doc),
                        "url": doc.url,
                        "query": doc.query,
                        "iteration": s.iteration_count,
                    }
                    for doc in npm_docs
                )
            cached = [
                e for e in store.query(s.as_of, mode) if e.extraction_version == EXTRACTION_VERSION
            ]
            existing = {e.document_id or e.evidence_id for e in cached}
            documents = [r for r in s.search_results if r.url != NPM_API_URL] + (
                store.recent_documents(s.as_of, mode) if not demo else []
            )
            documents = [r for r in documents if r.url != NPM_API_URL]
            unique = {result_id(r): r for r in documents}
            pending = [r for key, r in unique.items() if key not in existing]
            # Give each actual query space; a few official but irrelevant pages must not crowd out all factors.
            pending.sort(
                key=lambda r: (
                    -int("openai" in r.title.lower()),
                    -int("openai" in (r.title + r.content[:5000]).lower()),
                    -source_quality(r.url)[1],
                    r.published_at is None,
                )
            )
            groups = {}
            for doc in pending:
                topic = document_topic(doc.query)
                groups.setdefault(topic, []).append(doc)
            groups = {
                topic: sorted(groups[topic], key=lambda doc: document_priority(doc, topic))
                for topic in ("financing", "revenue", "profitability", "competition", "other")
                if topic in groups
            }
            pending = [
                docs[i]
                for i in range(max(map(len, groups.values()), default=0))
                for docs in groups.values()
                if i < len(docs)
            ]
            # A previously observed primary transaction must not disappear merely
            # because today's search ranks navigation pages above the announcement.
            from perception.evidence_extractor import official_closed_anchor

            anchors = [r for r in pending if official_closed_anchor(r)]
            pending = anchors[:1] + [r for r in pending if r not in anchors[:1]]
            if len(pending) > settings.max_documents_per_round:
                s.warnings.append("超出单轮证据处理上限；部分搜索结果仅存入原始状态，未参与推理。")
            new = extract(
                pending[: settings.max_documents_per_round],
                llm,
                s.as_of,
                settings.stale_days,
                settings.document_excerpt_chars,
                strict=False,
                warnings=s.warnings,
                source_timezone=rules.timezone,
            )
            s.processing_history.extend(
                {
                    "document_id": result_id(doc),
                    "url": doc.url,
                    "query": doc.query,
                    "iteration": s.iteration_count,
                }
                for doc in pending[: settings.max_documents_per_round]
            )
            store.save_evidence(new, mode)
            s.evidence_ids = sorted(
                set(s.evidence_ids)
                | {e.evidence_id for e in npm_evidence}
                | {e.evidence_id for e in new}
                | {e.evidence_id for e in cached if (e.document_id or e.evidence_id) in unique}
            )
            if not new:
                s.warnings.append("本轮未取得新内容，后续仅按已有证据推断。")

        def retrieve(s):
            candidates = [
                e for e in store.query(s.as_of, mode) if e.extraction_version == EXTRACTION_VERSION
            ]
            # Recompute recency at THIS cutoff, not the time a document was first inserted.
            candidates = [
                e.model_copy(
                    update={
                        "stale": bool(
                            e.published_at and (s.as_of - e.published_at).days > settings.stale_days
                        )
                    }
                )
                for e in candidates
            ]
            s.retrieved_evidence = vectors.retrieve(s.question, candidates, settings.retrieval_k)
            s.evidence_ids = [e.evidence_id for e in s.retrieved_evidence]

        def reasoning(s):
            s.hypotheses = reason(llm, s.retrieved_evidence, s.question, s.as_of)
            s.causal_relations = [
                {"from": a, "to": b, "evidence_ids": h.evidence_ids, "status": "Model Inference"}
                for h in s.hypotheses
                for a, b in zip(h.mechanism, h.mechanism[1:])
            ]

        def criticism(s):
            s.critique = critique(llm, s.retrieved_evidence, s.hypotheses, s.as_of)
            accepted = set(s.critique.accepted_evidence)
            targeted = []
            try:
                select_anchor(
                    [e for e in s.retrieved_evidence if e.evidence_id in accepted],
                    rules,
                    s.as_of,
                    mode,
                    settings.max_anchor_age_days,
                )
            except MissingAnchor:
                s.critique.missing_information.append("缺少符合配置口径、日期和来源要求的估值锚点")
                targeted = (
                    [
                        f"OpenAI Forge Price valuation as of {s.as_of.year} site:forgeglobal.com",
                        "OpenAI Forge Price valuation site:forgeglobal.com/insights",
                    ]
                    if rules.provider == "Forge"
                    else [
                        "OpenAI NPM Price implied valuation site:nasdaqprivatemarket.com/company/open-ai",
                        "OpenAI NPM Price OpenAI valuation site:fe.secondmarket.com",
                    ]
                    if rules.provider == "NPM"
                    else [
                        f"OpenAI latest completed funding valuation {s.as_of.year} site:openai.com",
                        f"OpenAI completed financing employee share sale valuation {s.as_of.year} site:reuters.com",
                    ]
                )
                s.critique.recommended_followup_queries = list(
                    dict.fromkeys(targeted + s.critique.recommended_followup_queries)
                )
            s.coverage = assess_coverage(s, settings)
            s.critique.missing_information.extend(s.coverage["gaps"])
            if not s.coverage["passed"]:
                s.critique.recommended_followup_queries = list(
                    dict.fromkeys(
                        targeted[:1]
                        + coverage_queries(s.coverage, s.as_of.year)
                        + s.critique.recommended_followup_queries
                    )
                )
            s.information_gaps = list(dict.fromkeys(s.critique.missing_information))

        def check(s):
            if s.information_gaps and not needs_followup(s, settings, budget):
                s.warnings.append("研究预算/迭代限制或无新增查询，保留未解决的信息缺口。")

        def belief(s):
            if not s.coverage["passed"]:
                raise InsufficientEvidence(
                    "Research acceptance failed: " + "; ".join(s.coverage["gaps"])
                )
            s.belief_state = update_belief(s, settings, rules)
            s.belief_state["rules_snapshot"] = rules.model_dump(mode="json")
            s.belief_state["settings_snapshot"] = settings.model_dump()

        def forecast(s):
            s.forecast = generate_forecast(s, rules)
            for previous in store.runs(mode):
                if (
                    previous.forecast
                    and previous.status == "completed"
                    and previous.run_id != s.run_id
                ):
                    try:
                        s.history_comparison = compare_runs(previous, s)
                        break
                    except ValueError:
                        continue

        def report(s):
            s.report_path = write_report(s, rules, output)

        def save(s):
            s.status = "completed"

        def wrapped(name, operation):
            def execute(graph_state):
                nonlocal latest
                s = CognitiveState.model_validate(graph_state["cognitive"])
                latest = s
                operation(s)
                s.trace.append(name)
                s.usage = budget.snapshot()
                s.warnings = list(dict.fromkeys(s.warnings))
                s = CognitiveState.model_validate(s.model_dump())
                latest = s
                store.snapshot(s, name)
                checkpoint = output / f"{s.run_id}.state.json"
                write_checkpoint(checkpoint, s.model_dump_json(indent=2))
                logger.info("run=%s step=%s iteration=%s", s.run_id, name, s.iteration_count)
                if on_step:
                    on_step(name, s)
                return {"cognitive": s.model_dump(mode="json")}

            return execute

        nodes = [
            ("ParseQuestion", parse),
            ("PlanResearch", plan),
            ("Search", search_node),
            ("ProcessEvidence", process),
            ("RetrieveMemory", retrieve),
            ("Reason", reasoning),
            ("Critique", criticism),
            ("CheckInformationSufficiency", check),
            ("UpdateBelief", belief),
            ("GenerateForecast", forecast),
            ("GenerateReport", report),
            ("SaveRun", save),
        ]
        graph = StateGraph(GraphState)
        for name, operation in nodes:
            graph.add_node(name, wrapped(name, operation))
        names = [name for name, _ in nodes]
        entry = names[0]
        if resume_node in names:
            if resume_node == "CheckInformationSufficiency":
                entry = "Search" if needs_followup(state, settings, budget) else "UpdateBelief"
            else:
                entry = names[min(names.index(resume_node) + 1, len(names) - 1)]
        graph.add_edge(START, resume_from or entry)
        for (name, _), (following, _) in zip(nodes, nodes[1:]):
            if name != "CheckInformationSufficiency":
                graph.add_edge(name, following)
        graph.add_conditional_edges(
            "CheckInformationSufficiency",
            lambda g: (
                "Search"
                if needs_followup(CognitiveState.model_validate(g["cognitive"]), settings, budget)
                and any(
                    q not in {r["query"] for r in g["cognitive"]["search_history"]}
                    for q in g["cognitive"]["critique"]["recommended_followup_queries"]
                )
                else "UpdateBelief"
            ),
            ["Search", "UpdateBelief"],
        )
        graph.add_edge("SaveRun", END)
        result = graph.compile().invoke(
            {"cognitive": state.model_dump(mode="json")},
            {"recursion_limit": settings.max_iterations * 10 + 20},
        )
        final = CognitiveState.model_validate(result["cognitive"])
        # Refresh the human-readable report with the final complete trace and usage.
        write_report(final, rules, output)
        return final
    except Exception as exc:
        latest.status = "failed"
        latest.usage = budget.snapshot()
        latest.warnings.append(f"{type(exc).__name__}: {exc}")
        latest.trace.append("Failed")
        store.snapshot(latest, "Failed")
        (output / f"{latest.run_id}.state.json").write_text(
            latest.model_dump_json(indent=2), encoding="utf-8"
        )
        raise
