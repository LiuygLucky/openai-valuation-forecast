"""Extract only explicit calendar days; never invent missing month/day components."""

import re
from datetime import date, datetime


def explicit_days(text: str) -> list[date]:
    found = []
    for y, m, d in re.findall(
        r"\b(20\d{2})\s*[-/年]\s*(\d{1,2})\s*[-/月]\s*(\d{1,2})(?:日|\b)", text
    ):
        try:
            found.append(date(int(y), int(m), int(d)))
        except ValueError:
            continue
    months = r"(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
    for month, day, year in re.findall(
        months + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?[,]?\s+(20\d{2})", text, re.I
    ):
        try:
            found.append(datetime.strptime(f"{month[:3]} {day} {year}", "%b %d %Y").date())
        except ValueError:
            continue
    return list(dict.fromkeys(found))


def normalized_quote(quote: str, source: str) -> bool:
    """Allow formatting-only whitespace differences, not semantic or numeric repair."""

    def normalize(x):
        return re.sub(r"\s+", " ", x.replace("\u200b", "")).strip()

    return bool(quote.strip()) and normalize(quote) in normalize(source)
