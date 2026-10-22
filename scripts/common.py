"""여러 스크립트가 함께 쓰는 도구 모음 (파일 위치, 저장, 날짜 처리)."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "docs" / "data"          # 웹페이지가 읽는 데이터
IMAGE_DIR = ROOT / "docs" / "images"       # 웹페이지에 보여줄 원본 식단표 이미지
STATE_FILE = ROOT / "state" / "processed.json"  # 이미 판독한 이미지 기록
INBOX_DIR = ROOT / "inbox"                 # 사람이 직접 올리는 식단표 사진
KEEP_DAYS = 42                             # 이 기간보다 오래된 식단은 정리

KST = dt.timezone(dt.timedelta(hours=9))

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def today_kst() -> dt.date:
    return dt.datetime.now(KST).date()


def now_kst_iso() -> str:
    return dt.datetime.now(KST).replace(microsecond=0).isoformat()


def load_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def split_menu(text: str) -> list[str]:
    """'쌀밥, 된장국, 제육(돼지, 국내산)' → ['쌀밥', '된장국', '제육(돼지, 국내산)']
    괄호 안의 쉼표는 나누지 않는다."""
    items, buf, depth = [], "", 0
    for ch in text:
        if ch in "([{（":
            depth += 1
        elif ch in ")]}）":
            depth = max(0, depth - 1)
        if ch in ",/\n·" and depth == 0:
            if buf.strip():
                items.append(buf.strip())
            buf = ""
        else:
            buf += ch
    if buf.strip():
        items.append(buf.strip())
    return [re.sub(r"\s+", " ", i) for i in items]


CLOSED_WORDS = ("미운영", "휴무", "운영안함", "운영 안함", "휴관", "공휴일")


def is_closed(text: str) -> bool:
    t = text.replace(" ", "")
    return any(w.replace(" ", "") in t for w in CLOSED_WORDS)


def load_restaurant(rid: str) -> dict:
    return load_json(DATA_DIR / f"{rid}.json", {"id": rid, "days": {}, "images": []})


def save_restaurant(rid: str, data: dict) -> None:
    """오래된 날짜를 정리한 뒤 저장한다."""
    cutoff = (today_kst() - dt.timedelta(days=KEEP_DAYS)).isoformat()
    data["days"] = {d: v for d, v in sorted(data.get("days", {}).items()) if d >= cutoff}
    data["images"] = [i for i in data.get("images", []) if i.get("week_end", "9999") >= cutoff]
    data["updated"] = now_kst_iso()
    save_json(DATA_DIR / f"{rid}.json", data)


def merge_days(data: dict, new_days: dict, meta: dict | None = None) -> int:
    """새로 읽은 날짜별 식단을 기존 데이터에 덮어쓴다. 바뀐 날짜 수를 돌려준다."""
    changed = 0
    days = data.setdefault("days", {})
    for date, meals in new_days.items():
        entry = {"meals": meals}
        if meta:
            entry.update(meta)
        if days.get(date) != entry:
            days[date] = entry
            changed += 1
    return changed
