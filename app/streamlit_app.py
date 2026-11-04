"""Run: python -m streamlit run app/streamlit_app.py"""

import json
import os
import sys
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.jobs import reconcile_jobs, start_live_job
from core.config import ROOT, MarketRules, load_config
from core.controller import run_forecast
from core.schemas import utcnow
from core.task_parser import parse_task
from evaluation.history import compare_runs
from forecasting.report import distribution_figure
from memory.evidence_store import EvidenceStore

st.set_page_config(page_title="认知事件预测 V1", page_icon="📊", layout="wide")
st.title("Cognitive Forecasting Agent V1")
st.caption("OpenAI NPM 隐含估值终点区间 · 证据可追溯 · 可复现数值模型")
settings, base_rules = load_config(os.getenv("FORECAST_SETTINGS"))
page = st.sidebar.radio("页面", ["预测任务", "认知研究过程", "预测结果", "预测历史"])
st.sidebar.info(
    f"当前指标：{base_rules.valuation_metric}（{base_rules.provider}）。区间由本研究设定；Polymarket 仅提供题目。"
)
state = st.session_state.get("forecast_state")

if page == "预测任务":
    mode = st.radio("运行模式", ["DEMO / SYNTHETIC（无需密钥）", "LIVE（需要本地 .env 密钥）"])
    demo = mode.startswith("DEMO")
    question = st.text_area("预测问题", "预测 OpenAI 在 2026 年 12 月 31 日的私募估值区间概率。")
    target = st.date_input("目标日期（配置时区当日 23:59:59）", base_rules.target_date.date())
    if demo:
        cutoff_date = st.date_input("信息截止日期（合成演示）", datetime(2026, 11, 2).date())
        cutoff = datetime.combine(cutoff_date, time(12), ZoneInfo("Asia/Singapore"))
        st.warning("演示数据完全合成，不能作为真实 OpenAI 估值结论。")
    else:
        cutoff = None
        st.info(
            "信息截止时间：本次实时研究采集结束时。实时搜索无法保证历史隔离，因此不开放历史回测。"
        )
        if base_rules.provider == "Forge":
            st.warning(
                "当前须取得 Forge 官方带观测日期的 OpenAI Forge Price Valuation；"
                "公开公司页可能隐藏最新值。找不到可核验报价时，LIVE 会保存失败状态而不编造概率。"
            )
        if base_rules.provider == "NPM":
            st.info(
                "LIVE 从 NPM 官方 OpenAI 数据页读取 implied_valuation（公司整体估值）作锚点，"
                "price（美元/股）另存；若官方数据不可达或过期则拒绝预测。"
            )
    intervals_json = st.text_area(
        "预测区间 JSON（单位 USD billion；末区间 upper 为 null）",
        json.dumps([i.model_dump() for i in base_rules.intervals], ensure_ascii=False, indent=2),
        height=220,
    )
    with st.expander("规则、计算参数与预算"):
        st.json(base_rules.model_dump(mode="json"))
        st.json(settings.model_dump())
    if st.button("开始预测", type="primary"):
        st.session_state.pop("forecast_state", None)
        try:
            values = base_rules.model_dump()
            values["target_date"] = datetime.combine(
                target, time(23, 59, 59), ZoneInfo(base_rules.timezone)
            )
            values["intervals"] = json.loads(intervals_json)
            rules = MarketRules.model_validate(values)
            parsed_rules, _ = parse_task(question, rules, cutoff or utcnow())
            if parsed_rules.target_date != rules.target_date:
                raise ValueError("问题中的日期与目标日期输入框不一致，请统一后运行。")
            if parsed_rules.intervals != rules.intervals:
                raise ValueError("问题中的区间与区间编辑框不一致，请统一后运行。")
            if demo:
                with st.status("正在执行认知研究流程…", expanded=True) as status:

                    def progress(name, current):
                        st.write(
                            f"{name} · 第 {current.iteration_count} 轮 · {len(current.evidence_ids)} 条证据"
                        )

                    result = run_forecast(
                        question, settings, rules, demo=True, as_of=cutoff, on_step=progress
                    )
                    st.session_state["forecast_state"] = result
                    status.update(
                        label="研究完成：请查看研究过程与预测结果", state="complete", expanded=False
                    )
                st.success(f"已保存预测 {result.run_id}")
            else:
                run_id = start_live_job(question, settings, rules)
                st.session_state["active_run_id"] = run_id
                st.success(
                    f"LIVE 研究已在后台启动：{run_id}。可切换到预测历史，页面会自动刷新状态。"
                )
        except Exception as exc:
            st.error(f"未生成预测：{exc}")
            if "ConnectError" in str(exc):
                st.info(
                    "模型服务网络连接失败，尚未开始搜索，也未检查估值锚点。"
                    "请从能访问外网的 PowerShell 启动此页面，再重试 LIVE。"
                )
            else:
                st.info("失败状态保存在本地历史记录中。请按上方具体错误排查。")

elif page == "认知研究过程":
    if state is None:
        st.info("请先执行预测，或在预测历史中载入记录。")
    else:
        st.write(f"运行模式：{state.mode.upper()} · 搜索迭代：{state.iteration_count}")
        st.subheader("研究计划")
        st.dataframe(pd.DataFrame([p.model_dump() for p in state.research_plan]), hide_index=True)
        st.subheader("搜索查询")
        st.dataframe(pd.DataFrame(state.search_history), hide_index=True)
        st.subheader("证据与原始来源")
        for e in state.retrieved_evidence:
            with st.expander(f"{e.category} · {e.epistemic_status} · {e.title}"):
                st.write(e.claim)
                st.link_button("原始来源", e.source_url)
                st.json(e.model_dump(mode="json"))
        st.subheader("因果机制假设（不是因果识别结论）")
        st.json([h.model_dump() for h in state.hypotheses])
        st.subheader("独立反方审查")
        st.json(state.critique.model_dump() if state.critique else {})
        st.subheader("任务解析与覆盖验收")
        st.json(state.task_spec)
        st.json(state.coverage)
        st.write(" → ".join(state.trace))
        st.json(state.usage)

elif page == "预测结果":
    if state is None or state.forecast is None:
        st.info("尚无可显示的预测结果。")
    else:
        f = state.forecast
        if state.mode == "demo":
            st.warning("DEMO / SYNTHETIC：图表和数字来自合成测试数据。")
        st.caption(
            f"指标 {f.valuation_metric} · 信息截止 {f.as_of.isoformat()} · 目标 {f.target_date.isoformat()}"
        )
        a, b, c = st.columns(3)
        a.metric("模型中位数（USD billion）", f"{f.median_valuation:,.2f}")
        b.metric("90% 模型区间下界", f"{f.confidence_interval_90[0]:,.2f}")
        c.metric("90% 模型区间上界", f"{f.confidence_interval_90[1]:,.2f}")
        st.plotly_chart(distribution_figure(state), width="stretch")
        hist = state.belief_state["histogram"]
        centers = [(x + y) / 2 for x, y in zip(hist["edges"], hist["edges"][1:])]
        fig = go.Figure(go.Bar(x=centers, y=hist["counts"]))
        fig.update_layout(
            title="终点估值模拟分布", xaxis_title="USD billion", yaxis_title="样本数量"
        )
        st.plotly_chart(fig, width="stretch")
        st.subheader("主要影响因素及参数")
        st.dataframe(pd.DataFrame(state.belief_state["event_adjustments"]), hide_index=True)
        st.subheader("主要风险与局限")
        for item in f.limitations:
            st.write(f"- {item}")
        st.download_button(
            "下载预测 JSON", f.model_dump_json(indent=2), "forecast.json", "application/json"
        )
        if state.report_path and Path(state.report_path).is_file():
            st.download_button(
                "下载 Markdown 报告",
                Path(state.report_path).read_text(encoding="utf-8"),
                "report.md",
                "text/markdown",
            )
        st.download_button(
            "下载完整审计状态", state.model_dump_json(indent=2), "state.json", "application/json"
        )

else:

    @st.fragment(run_every="5s")
    def render_history():
        reconcile_jobs(settings)
        history_mode = st.radio("历史数据类型", ["demo", "live"])
        history = EvidenceStore(ROOT / settings.database).runs(history_mode)
        if not history:
            st.info("尚无此类型历史记录。")
        else:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "run_id": s.run_id,
                            "as_of": s.as_of.isoformat(),
                            "status": s.status,
                            "model_version": s.forecast.model_version if s.forecast else "v1.0",
                            "probabilities": {
                                p.interval: p.probability for p in s.forecast.probabilities
                            }
                            if s.forecast
                            else {},
                        }
                        for s in history
                    ]
                ),
                hide_index=True,
            )
            selected = st.selectbox(
                "查看记录",
                history,
                format_func=lambda s: f"{s.generated_at.isoformat()} / {s.run_id[:8]} / {s.status}",
            )
            if st.button("载入所选记录"):
                st.session_state["forecast_state"] = selected
                st.success("已载入；可切换到研究过程或结果页面。")
            if selected.status == "failed":
                st.json(selected.warnings)
            complete = [s for s in history if s.forecast and s.status == "completed"]
            if len(complete) >= 2:
                old = st.selectbox(
                    "比较：较早记录", complete, index=1, format_func=lambda s: s.run_id
                )
                new = st.selectbox("比较：较新记录", complete, format_func=lambda s: s.run_id)
                try:
                    delta = compare_runs(old, new)
                    st.dataframe(pd.DataFrame(delta["probability_changes"]), hide_index=True)
                    for explanation in delta["explanations"]:
                        st.write(explanation)
                    st.json(delta)
                except ValueError as exc:
                    st.warning(str(exc))

    render_history()
