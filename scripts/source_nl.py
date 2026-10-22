"""국립중앙도서관 식단표 (웹페이지에 글자로 올라옴 → 바로 읽음)."""
from __future__ import annotations

import datetime as dt
import re

import requests
from bs4 import BeautifulSoup

from common import UA, is_closed, split_menu

URL = "https://www.nl.go.kr/NL/contents/N40501020000.do"
DATE_RE = re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")
MEAL_ORDER = ("조식", "중식", "간편식", "석식")


def _meal(label: str, text: str) -> dict:
    text = text.strip()
    if not text or is_closed(text):
        return {"label": label, "items": [], "closed": True}
    return {"label": label, "items": split_menu(text), "closed": False}


def parse(html: str) -> dict[str, list[dict]]:
    """HTML에서 {'2026-10-20': [{'label': '중식', 'items': [...]}, ...]} 를 뽑는다."""
    soup = BeautifulSoup(html, "html.parser")
    days: dict[str, list[dict]] = {}

    # 방법 1: 표(table)마다 바로 앞에 있는 날짜 글자를 찾는다.
    for table in soup.find_all("table"):
        headers = [c.get_text(" ", strip=True) for c in table.find_all("th")]
        if not any(h in MEAL_ORDER for h in headers):
            continue
        prev = table.find_previous(string=DATE_RE)
        if not prev:
            continue
        y, m, d = map(int, DATE_RE.search(prev).groups())
        date = dt.date(y, m, d).isoformat()
        cells = [c.get_text(" ", strip=True) for c in table.find_all("td")]
        meal_headers = [h for h in headers if h in MEAL_ORDER]
        meals = [_meal(h, cells[i] if i < len(cells) else "") for i, h in enumerate(meal_headers)]
        days[date] = meals

    if days:
        return days

    # 방법 2 (예비): 표 구조가 바뀌었을 때 글자 흐름으로 읽는다.
    lines = [l.strip() for l in soup.get_text("\n").split("\n") if l.strip()]
    i = 0
    while i < len(lines):
        m = DATE_RE.search(lines[i])
        if not m:
            i += 1
            continue
        date = dt.date(*map(int, m.groups())).isoformat()
        j = i + 1
        labels = []
        while j < len(lines) and lines[j] in MEAL_ORDER + ("월", "화", "수", "목", "금", "토", "일"):
            if lines[j] in MEAL_ORDER:
                labels.append(lines[j])
            j += 1
        values = []
        while j < len(lines) and len(values) < len(labels) and not DATE_RE.search(lines[j]):
            if not lines[j].startswith("식당 식단표"):
                values.append(lines[j])
            j += 1
        if labels and values:
            days[date] = [_meal(lb, values[k] if k < len(values) else "") for k, lb in enumerate(labels)]
        i = j
    return days


def fetch() -> dict[str, list[dict]]:
    r = requests.get(URL, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    days = parse(r.text)
    if not days:
        raise RuntimeError("국립중앙도서관 페이지에서 식단을 찾지 못했습니다 (페이지 구조 변경 가능성).")
    return days
