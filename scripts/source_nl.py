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
    if is_closed(text):
        return {"label": label, "items": [], "closed": True}
    return {"label": label, "items": split_menu(text), "closed": False}


def parse(html: str) -> dict[str, list[dict]]:
    """HTML에서 {'2026-10-20': [{'label': '중식', 'items': [...]}, ...]} 를 뽑는다."""
    soup = BeautifulSoup(html, "html.parser")
    days: dict[str, list[dict]] = {}

    # 방법 1: 표(table)마다 바로 앞에 있는 날짜 글자를 찾는다.
    #  - 날짜가 여러 태그로 쪼개져 있어도(<b>2026</b>년 …) 찾도록 '요소 전체 글자'로 검사한다.
    #  - 머리칸이 <th>가 아니라 <td>여도 읽는다.
    def has_date(tag) -> bool:
        if tag.name in ("table", "script", "style", "body", "html") or tag.find("table"):
            return False
        return bool(DATE_RE.search(tag.get_text(" ", strip=True)))

    for table in soup.find_all("table"):
        rows = [[c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])] for tr in table.find_all("tr")]
        rows = [r for r in rows if r]
        if len(rows) < 2:
            continue
        headers = rows[0]
        meal_cols = [(i, h.replace(" ", "")) for i, h in enumerate(headers) if h.replace(" ", "") in MEAL_ORDER]
        if not meal_cols:
            continue
        date_text = ""
        caption = table.find("caption")
        if caption and DATE_RE.search(caption.get_text(" ")):
            date_text = caption.get_text(" ")
        else:
            prev = table.find_previous(has_date)
            date_text = prev.get_text(" ", strip=True) if prev else ""
        m = DATE_RE.search(date_text)
        if not m:
            continue
        date = dt.date(*map(int, m.groups())).isoformat()
        values = rows[1]
        days[date] = [_meal(h, values[i] if i < len(values) else "") for i, h in meal_cols]

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
    # 페이지가 알려 주는 글자 인코딩을 우선 쓰고, 없으면 UTF-8 (자동 추측은 한글을 깨뜨릴 수 있음)
    if "charset" not in r.headers.get("Content-Type", "").lower():
        r.encoding = "utf-8"
    days = parse(r.text)
    if not days:
        # 원인 확인용으로 받은 페이지를 저장해 둔다 (state/debug/nl.html).
        from common import ROOT
        debug = ROOT / "state" / "debug"
        debug.mkdir(parents=True, exist_ok=True)
        (debug / "nl.html").write_text(r.text, encoding="utf-8")
        raise RuntimeError(f"국립중앙도서관 페이지에서 식단을 찾지 못했습니다 (응답 {r.status_code}, {len(r.text)}자).")
    return days
