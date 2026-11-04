"""Parse the supported OpenAI task domain without adding an LLM dependency to offline mode."""

import re
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from core.config import MarketRules
from perception.dates import explicit_days


def parse_task(question: str, rules: MarketRules, as_of: datetime) -> tuple[MarketRules, dict]:
    lower = question.casefold()
    if "openai" not in lower or not any(x in lower for x in ("估值", "valuation", "equity value")):
        raise ValueError("V1 supports an explicit OpenAI equity valuation question")
    if any(x in lower for x in ("最高", "曾经", "触及", "ever reach", "maximum", "hit before")):
        raise ValueError("Path/barrier events are not terminal interval events")
    values = rules.model_dump()
    dates = explicit_days(question)
    for year in re.findall(r"(20\d{2})\s*(?:年\s*)?(?:年底|年末|year.end)", lower):
        dates.append(date(int(year), 12, 31))
    for year in re.findall(r"(?:end of|year.end)\s*(20\d{2})", lower):
        dates.append(date(int(year), 12, 31))
    for year in re.findall(r"(20\d{2})\s*年\s*12\s*月\s*(?:底|末|31\s*日)", question):
        dates.append(date(int(year), 12, 31))
    relative_end = re.findall(
        r"(今|明|后|本|来)年\s*(?:的\s*)?(?:年?底|年?末|年终|年尾|12\s*月\s*(?:底|末|31\s*日))",
        question,
    )
    for word in relative_end:
        dates.append(date(as_of.year + {"今": 0, "本": 0, "明": 1, "来": 1, "后": 2}[word], 12, 31))
    dates = list(dict.fromkeys(dates))
    if re.search(r"第?[一二三四1-4]季度|Q[1-4]|next\s+quarter", question, re.I):
        raise ValueError("Quarter targets require an explicit calendar day")
    mentioned_years = {int(year) for year in re.findall(r"20\d{2}", question)}
    if dates and mentioned_years - {day.year for day in dates}:
        raise ValueError("Multiple or incomplete target years are ambiguous")
    if not dates and re.search(
        r"20\d{2}|今[年]|明[年]|后[年]|本年|来年|年底|年末|年终|年尾|"
        r"\d{1,2}\s*月|\b\d{1,2}[/-]\d{1,2}\b|月底|月末|"
        r"下周|下月|半年|季度|个月|春节|元旦|圣诞|国庆|"
        r"第?[一二三四1-4]季度|Q[1-4]|"
        r"this\s+year|next\s+year|end\s+of\s+year|year[ -]?end|"
        r"\b(?:future|tomorrow|next\s+month|next\s+quarter)\b",
        question,
        re.I,
    ):
        raise ValueError(
            "Question mentions a target time that cannot be resolved to a calendar day; "
            "specify a full date or a supported year-end expression"
        )
    if len(dates) > 1:
        raise ValueError(
            "Multiple target dates are ambiguous; use the separate information-cutoff input"
        )
    if re.search(r"\d{1,2}:\d{2}", question):
        raise ValueError("Intraday target times must be set explicitly in the rules configuration")
    origins = {
        "target_date": "question" if dates else "configuration",
        "intervals": "configuration",
        "metric": "configuration",
        "timezone": "configuration",
    }
    if dates:
        values["target_date"] = datetime.combine(
            dates[0], time(23, 59, 59), ZoneInfo(rules.timezone)
        )
    providers = [p for p in ("NPM", "Forge") if re.search(r"\b" + p + r"\b", question, re.I)]
    if len(providers) > 1:
        raise ValueError("Forge and NPM are distinct metrics; select one provider")
    if providers:
        values["provider"] = providers[0]
        values["valuation_metric"] = (
            "Forge_Price_Valuation" if providers[0] == "Forge" else "NPM_implied_equity_valuation"
        )
        origins["metric"] = "question"
    elif "融资" in question or "financing proxy" in lower:
        values["provider"] = "financing_proxy"
        values["valuation_metric"] = "private_company_equity_valuation_proxy"
        origins["metric"] = "question"
    match = re.search(
        r"(?:区间边界|interval boundaries)\s*(?:[（(][^）)]*[）)])?\s*[:：]\s*([\d.,，\s]+)",
        question,
        re.I,
    )
    if match:
        if "万亿美元" in question or "trillion" in lower:
            scale = 1000
        elif "十亿美元" in question or "billion" in lower:
            scale = 1
        elif "亿美元" in question:
            scale = 0.1
        else:
            raise ValueError(
                "Explicit interval boundaries require a unit: 十亿美元 / 亿美元 / USD billion"
            )
        numbers = [float(x) * scale for x in re.findall(r"\d+(?:\.\d+)?", match.group(1))]
        if not numbers or numbers != sorted(set(numbers)) or numbers[0] <= 0:
            raise ValueError("Interval boundaries must be positive and strictly increasing")
        edges = [0.0] + numbers
        values["intervals"] = [
            {
                "label": (
                    f"<{numbers[0]:g}B"
                    if i == 0
                    else f"≥{lo:g}B"
                    if i == len(edges) - 1
                    else f"{lo:g}–{edges[i + 1]:g}B"
                ),
                "lower": lo,
                "upper": edges[i + 1] if i + 1 < len(edges) else None,
            }
            for i, lo in enumerate(edges)
        ]
        origins["intervals"] = "question"
    elif re.search(r"(?:区间|intervals?)\s*[:：]", question, re.I):
        raise ValueError("Use explicit 区间边界（十亿美元）：500,750,1000 or the interval editor")
    result = MarketRules.model_validate(values)
    if result.target_date <= as_of:
        raise ValueError("Target date must follow information cutoff")
    return result, {
        "entity": "OpenAI",
        "forecast_type": "terminal_interval",
        "target_date": result.target_date.isoformat(),
        "as_of": as_of.isoformat(),
        "provider": result.provider,
        "unit": result.unit,
        "timezone": result.timezone,
        "intervals": [x.model_dump() for x in result.intervals],
        "field_origins": origins,
    }
