"""서울지방조달청 식단표 (게시판에 주간 식단표 이미지가 첨부됨 → 새 글일 때만 판독)."""
from __future__ import annotations

import datetime as dt
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from common import UA

BASE = "https://www.pps.go.kr"
LIST_URL = BASE + "/seoul/bbs/list.do?key=01319"
TITLE_RE = re.compile(r"(\d{1,2})\s*\.\s*(\d{1,2})\s*\.?\s*[~∼～-]\s*(\d{1,2})\s*\.\s*(\d{1,2})")
FILE_RE = re.compile(r"fileDown\.do[^\"'\s>]*?key=(\d+)(?:&amp;|&)sn=(\d+)")
POSTED_RE = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")


def _strip_session(url: str) -> str:
    return re.sub(r";jsessionid=[^?#]*", "", url)


def parse_list(html: str) -> list[dict]:
    """게시판 목록에서 최근 식단표 글들을 뽑는다 (최신 글이 먼저)."""
    soup = BeautifulSoup(html, "html.parser")
    posts = []
    for tr in soup.find_all("tr"):
        text = tr.get_text(" ", strip=True)
        if "식단" not in text:
            continue
        link = tr.find("a", href=FILE_RE)
        if not link:
            continue
        fm = FILE_RE.search(link["href"])
        title_m = TITLE_RE.search(text)
        posted_m = POSTED_RE.search(text)
        posted = dt.date(*map(int, posted_m.groups())) if posted_m else None
        start = end = None
        if title_m and posted:
            m1, d1, m2, d2 = map(int, title_m.groups())
            y1 = posted.year + (1 if m1 < posted.month - 6 else 0)   # 12월 말 게시 → 다음 해 1월 식단
            y2 = y1 + (1 if m2 < m1 else 0)
            start, end = dt.date(y1, m1, d1), dt.date(y2, m2, d2)
        title_cell = tr.find(string=re.compile("식단"))
        posts.append({
            "key": fm.group(1),
            "sn": fm.group(2),
            "title": title_cell.strip() if title_cell else text[:40],
            "posted": posted.isoformat() if posted else "",
            "week_start": start.isoformat() if start else "",
            "week_end": end.isoformat() if end else "",
            "file_url": _strip_session(urljoin(BASE, link["href"].replace("&amp;", "&"))),
        })
    return posts


def fetch_list(session: requests.Session) -> list[dict]:
    r = session.get(LIST_URL, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    posts = parse_list(r.text)
    if not posts:
        raise RuntimeError("조달청 게시판에서 식단표 글을 찾지 못했습니다 (페이지 구조 변경 가능성).")
    return posts


def download(session: requests.Session, post: dict) -> tuple[bytes, str]:
    r = session.get(post["file_url"], headers={"User-Agent": UA, "Referer": LIST_URL}, timeout=60)
    r.raise_for_status()
    ctype = r.headers.get("Content-Type", "").split(";")[0].strip().lower()
    data = r.content
    if data[:8].startswith(b"\x89PNG"):
        ctype = "image/png"
    elif data[:3] == b"\xff\xd8\xff":
        ctype = "image/jpeg"
    elif data[:4] == b"GIF8":
        ctype = "image/gif"
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        ctype = "image/webp"
    if not ctype.startswith("image/"):
        raise RuntimeError(f"첨부파일이 이미지가 아닙니다 (형식: {ctype or '알 수 없음'}).")
    return data, ctype
