import html
import json
from pathlib import Path

import plotly.graph_objects as go


def distribution_figure(state):
    fig = go.Figure()
    for name, rows in [
        ("Evidence adjusted (heuristic)", state.forecast.probabilities),
        ("No-news baseline", state.forecast.baseline_probabilities),
    ]:
        fig.add_bar(name=name, x=[p.interval for p in rows], y=[p.probability for p in rows])
    fig.update_layout(
        title=("DEMO / SYNTHETIC — " if state.mode == "demo" else "")
        + "Terminal valuation probabilities",
        yaxis_tickformat=".0%",
        xaxis_title="USD billion",
        barmode="group",
    )
    return fig


def svg_chart(state):
    """Dependency-free static export alongside the interactive Plotly chart."""
    rows = state.forecast.probabilities
    height = 80 + len(rows) * 45
    chunks = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="760" height="{height}" viewBox="0 0 760 {height}">',
        '<rect width="100%" height="100%" fill="#f8fafc"/>',
        f'<text x="20" y="28" font-family="sans-serif" font-size="18">{state.mode.upper()} — terminal probabilities (USD billion)</text>',
    ]
    for i, p in enumerate(rows):
        y = 55 + i * 45
        chunks.extend(
            [
                f'<text x="20" y="{y + 20}" font-family="sans-serif">{html.escape(p.interval)}</text>',
                f'<rect x="160" y="{y}" width="{500 * p.probability:.2f}" height="28" fill="#2563eb"/>',
                f'<text x="{170 + 500 * p.probability:.2f}" y="{y + 20}" font-family="sans-serif">{p.probability:.2%}</text>',
            ]
        )
    return "\n".join(chunks + ["</svg>"])


def render_markdown(state, rules):
    f = state.forecast
    lines = [
        "# Cognitive Forecasting Agent V1 研究报告",
        "",
        "**DEMO / SYNTHETIC：以下全部事件和估值均为合成测试数据，不代表真实 OpenAI 预测。**"
        if state.mode == "demo"
        else "**LIVE / HEURISTIC：外部证据驱动的启发式预测，未经概率校准。**",
        "",
        "## 1. 任务与结算口径",
        f"- Run ID：`{state.run_id}`",
        f"- 问题：{f.question}",
        f"- 信息截止：{f.as_of.isoformat()}",
        f"- 目标时点：{f.target_date.isoformat()}",
        f"- 指标：{f.valuation_metric}；单位：USD billion；时区：{rules.timezone}",
        f"- 规则来源：{f.market_rules_source}",
        f"- 规则确认状态：{rules.rules_status}",
        f"- 边界：{rules.boundary_rule}",
        f"- 数据缺失：{rules.missing_data_rule}",
        f"- IPO：{rules.ipo_rule}",
        f"- 更新规则：{rules.update_rule}",
        "- 终点估值区间与期间最高值触及阈值不是同一预测任务。",
        "",
        "## 2. 当前证据与来源",
        "",
    ]
    for e in state.retrieved_evidence:
        accepted = state.critique and e.evidence_id in state.critique.accepted_evidence
        lines.extend(
            [
                f"- **[{e.evidence_id}] {e.epistemic_status} / {e.claim_kind} / {e.category} / {'审查通过' if accepted else '未接受或争议'}** — {e.claim}",
                f"  - [{e.title}]({e.source_url})；来源类型 {e.source_type}；可信度筛选分 {e.confidence:.2f}",
                f"  - 公开：{e.published_at}；事件：{e.event_at or 'Unknown'}；检索：{e.retrieved_at}；过时：{e.stale}",
                f"  - 事件日期依据：{e.event_time_basis}；日期原文：{e.event_date_quote or 'Unknown'}",
                f"  - 公开时间依据：{e.published_time_basis}",
            ]
        )
    for title, direction in [("3. 正面因素", "positive"), ("4. 负面因素", "negative")]:
        lines += ["", f"## {title}"]
        selected = [
            e
            for e in state.retrieved_evidence
            if e.impact_direction in (direction, "mixed")
            and state.critique
            and e.evidence_id in state.critique.accepted_evidence
        ]
        lines += [f"- [{e.evidence_id}] {e.claim}" for e in selected] or [
            "- 未找到足够证据；不表示不存在该类因素。"
        ]
    lines += ["", "## 5. 可追溯因果假设", "以下是机制假设，并非已经识别出的无偏因果效应。"]
    for h in state.hypotheses:
        lines += [
            f"### {h.event}",
            f"- 路径：{' → '.join(h.mechanism)}",
            f"- 证据：{', '.join(h.evidence_ids)}；方向：{h.direction}；已计价可能性：{h.priced_in}",
            f"- 相反解释：{'；'.join(h.counterarguments)}",
            f"- 不确定性：{'；'.join(h.uncertainties)}",
        ]
    lines += ["", "## 6. 信息缺口与独立审查"]
    lines += [f"- {g}" for g in state.information_gaps]
    if state.critique:
        lines += [f"- 争议/排除证据：{state.critique.disputed_evidence}"]
        lines += [f"- 偏差：{p}" for p in state.critique.potential_biases]
    lines += [
        "",
        "### 研究覆盖验收",
        "```json",
        json.dumps(state.coverage, ensure_ascii=False, indent=2),
        "```",
    ]
    lines += [
        "",
        "## 7. 概率与无新闻基准",
        "",
        "| 终点区间（USD billion） | 信念更新模型 | 锚点基准 | 差异（百分点） |",
        "|---|---:|---:|---:|",
    ]
    lines += [
        f"| {p.interval} | {p.probability:.4%} | {b.probability:.4%} | "
        f"{(p.probability - b.probability) * 100:+.4f} |"
        for p, b in zip(f.probabilities, f.baseline_probabilities, strict=True)
    ]
    lines += [
        "",
        "![概率分布](probabilities.svg)",
        "",
        "[交互式概率图](probabilities.html)",
        "[终点估值模拟分布](terminal_distribution.html)",
        "",
        "## 8. 数值计算与假设",
        "锚点前已公开的未来预测不视为新价格冲击；若有证据和方向明确的未来兑现风险，"
        "模型添加零均值情景以改变分布形状。该情景权重和幅度是未校准假设。",
        "```json",
        json.dumps(
            {k: v for k, v in state.belief_state.items() if k != "histogram"},
            ensure_ascii=False,
            indent=2,
        ),
        "```",
        "",
        "## 9. 当前结论",
        f"模型中位数：**{f.median_valuation:.2f} USD billion**；90% 模型区间："
        f"**[{f.confidence_interval_90[0]:.2f}, {f.confidence_interval_90[1]:.2f}]**。",
        "最终区间概率由固定种子的蒙特卡洛样本频率产生，不由 LLM 直接给定。",
        "",
        "## 10. 局限性、预算与研究轨迹",
    ]
    lines += [f"- {s}" for s in f.limitations]
    lines += [
        f"- 状态流程：{' → '.join(state.trace)}",
        f"- 迭代次数：{state.iteration_count}",
        f"- 使用量（成本为配置估计，不是账单）：{state.usage}",
        "",
        "### 实际搜索记录",
    ]
    lines += [f"- {q}" for q in state.search_history]
    lines += ["", "## 11. 与历史预测比较"]
    if state.history_comparison:
        lines += [f"- {s}" for s in state.history_comparison["explanations"]]
    else:
        lines += ["尚无同口径的已完成历史预测；不虚构历史变化。"]
    return "\n".join(lines) + "\n"


def write_report(state, rules, output_dir):
    folder = Path(output_dir) / state.mode / state.run_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "probabilities.svg").write_text(svg_chart(state), encoding="utf-8")
    distribution_figure(state).write_html(folder / "probabilities.html", include_plotlyjs=True)
    hist = state.belief_state["histogram"]
    centers = [(a + b) / 2 for a, b in zip(hist["edges"], hist["edges"][1:])]
    density = go.Figure(go.Bar(x=centers, y=hist["counts"]))
    density.update_layout(
        title="Terminal valuation distribution / " + state.mode.upper(),
        xaxis_title="USD billion",
        yaxis_title="Monte Carlo sample count",
    )
    density.write_html(folder / "terminal_distribution.html", include_plotlyjs=True)
    (folder / "state.json").write_text(state.model_dump_json(indent=2), encoding="utf-8")
    (folder / "forecast.json").write_text(
        state.forecast.model_dump_json(indent=2), encoding="utf-8"
    )
    path = folder / "report.md"
    path.write_text(render_markdown(state, rules), encoding="utf-8")
    return str(path.resolve())
