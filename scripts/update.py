"""매일 실행되는 본체: 식단 수집 → (필요할 때만) 이미지 판독 → 웹페이지용 데이터 생성.

실행: python scripts/update.py
"""
from __future__ import annotations

import datetime as dt
import io
import sys
import traceback

import requests

import ocr
import source_nl
import source_pps
from common import (DATA_DIR, IMAGE_DIR, INBOX_DIR, ROOT, STATE_FILE, load_json, load_restaurant,
                    merge_days, now_kst_iso, save_json, save_restaurant, sha256, today_kst)

IMAGE_EXT = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
             ".webp": "image/webp", ".gif": "image/gif", ".heic": "image/heic", ".heif": "image/heic"}

status: dict[str, dict] = {}


def warn(rid: str, message: str) -> None:
    print(f"::warning title={rid}::{message}")
    status.setdefault(rid, {})["problem"] = message


def run_nl() -> None:
    days = source_nl.fetch()
    data = load_restaurant("nl")
    changed = merge_days(data, days, {"source": "text"})
    save_restaurant("nl", data)
    print(f"[국립중앙도서관] {len(days)}일치 확인, {changed}일 변경")


def _record_image(data: dict, record: dict) -> None:
    data.setdefault("images", [])
    data["images"] = [i for i in data["images"] if i.get("path") != record["path"]]
    data["images"].append(record)
    data["images"].sort(key=lambda i: i.get("week_start") or i.get("read_at", ""), reverse=True)


def _apply_ocr(rid: str, data: dict, result: dict, record: dict) -> int:
    meta = {"source": "image", "image": record["path"], "verified": result["verified"]}
    disputed_dates = {d.split(" ")[0] for d in result["disputed"]}
    changed = 0
    for date, meals in result["days"].items():
        entry_meta = dict(meta, verified=result["verified"] or date not in disputed_dates)
        changed += merge_days(data, {date: meals}, entry_meta)
    dates = sorted(result["days"])
    if dates:
        record.setdefault("week_start", dates[0])
        record.setdefault("week_end", dates[-1])
        record["week_start"] = record["week_start"] or dates[0]
        record["week_end"] = record["week_end"] or dates[-1]
    record.update(verified=result["verified"], disputed=result["disputed"],
                  notes=result.get("notes", ""), model=result.get("model", ""), read_at=now_kst_iso())
    return changed


def run_pps(state: dict) -> None:
    session = requests.Session()
    posts = source_pps.fetch_list(session)
    recent_cut = (today_kst() - dt.timedelta(days=3)).isoformat()
    targets = [p for p in posts[:3] if not p["week_end"] or p["week_end"] >= recent_cut]
    data = load_restaurant("pps")
    for post in targets:
        state_key = f"pps:{post['key']}:{post['sn']}"
        if state_key in state:
            print(f"[조달청] {post['title']} — 이미 판독함, 건너뜀")
            continue
        img, ctype = source_pps.download(session, post)
        ext = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}[ctype]
        rel = f"images/pps/{post['key']}.{ext}"
        (IMAGE_DIR / "pps").mkdir(parents=True, exist_ok=True)
        (ROOT / "docs" / rel).write_bytes(img)
        record = {"path": rel, "title": post["title"], "posted": post["posted"],
                  "week_start": post["week_start"], "week_end": post["week_end"],
                  "source_url": source_pps.LIST_URL}
        if not ocr.available():
            record["pending"] = True
            _record_image(data, record)
            warn("pps", "ANTHROPIC_API_KEY가 없어 식단표 이미지를 판독하지 못했습니다. 원본 이미지만 표시합니다.")
            continue
        context = (f"서울지방조달청 구내식당. 게시글 제목 '{post['title']}', 게시일 {post['posted']}. "
                   f"식단 기간은 {post['week_start']} ~ {post['week_end']}로 추정된다.")
        result = ocr.transcribe(img, ctype, context)
        changed = _apply_ocr("pps", data, result, record)
        _record_image(data, record)
        state[state_key] = {"sha256": sha256(img), "read_at": now_kst_iso(), "verified": result["verified"]}
        flag = "교차검증 일치" if result["verified"] else f"확인 필요: {', '.join(result['disputed'])}"
        print(f"[조달청] {post['title']} 판독 완료 ({flag}), {changed}일 변경")
    save_restaurant("pps", data)


def _to_jpeg_if_heic(raw: bytes, ctype: str) -> tuple[bytes, str]:
    if ctype != "image/heic":
        return raw, ctype
    from PIL import Image
    from pillow_heif import register_heif_opener

    register_heif_opener()
    buf = io.BytesIO()
    Image.open(io.BytesIO(raw)).convert("RGB").save(buf, "JPEG", quality=92)
    return buf.getvalue(), "image/jpeg"


def run_inbox(rid: str, name: str, state: dict) -> None:
    folder = INBOX_DIR / rid
    files = sorted(p for p in folder.glob("*") if p.suffix.lower() in IMAGE_EXT) if folder.exists() else []
    if not files:
        return
    data = load_restaurant(rid)
    for path in files:
        raw = path.read_bytes()
        digest = sha256(raw)
        state_key = f"{rid}:{digest[:16]}"
        if state_key in state:
            continue
        if not ocr.available():
            warn(rid, f"ANTHROPIC_API_KEY가 없어 '{path.name}' 사진을 판독하지 못했습니다.")
            continue
        img, ctype = _to_jpeg_if_heic(raw, IMAGE_EXT[path.suffix.lower()])
        ext = "jpg" if ctype == "image/jpeg" else ctype.split("/")[1]
        rel = f"images/{rid}/{digest[:12]}.{ext}"
        (IMAGE_DIR / rid).mkdir(parents=True, exist_ok=True)
        (ROOT / "docs" / rel).write_bytes(img)
        context = (f"{name}. 오늘은 {today_kst().isoformat()} ({'월화수목금토일'[today_kst().weekday()]}요일)이다. "
                   "사람이 직접 찍어 올린 식단표 사진이므로 기울어짐·빛 반사가 있을 수 있다. "
                   "날짜에 연도가 없으면 오늘과 가장 가까운 날짜로 연도를 정한다.")
        result = ocr.transcribe(img, ctype, context)
        record = {"path": rel, "title": path.name, "posted": today_kst().isoformat(),
                  "week_start": "", "week_end": "", "source_url": ""}
        changed = _apply_ocr(rid, data, result, record)
        _record_image(data, record)
        state[state_key] = {"file": path.name, "read_at": now_kst_iso(), "verified": result["verified"]}
        print(f"[{name}] '{path.name}' 판독 완료, {changed}일 변경")
    save_restaurant(rid, data)


def build_index(restaurants: list[dict]) -> None:
    """웹페이지가 읽는 하나의 파일(menus.json)로 합친다."""
    out = {"updated": now_kst_iso(), "restaurants": []}
    for r in restaurants:
        data = load_restaurant(r["id"])
        entry = dict(r)
        entry["days"] = data.get("days", {})
        entry["images"] = data.get("images", [])[:4]
        entry["data_updated"] = data.get("updated", "")
        entry["problem"] = status.get(r["id"], {}).get("problem", "")
        out["restaurants"].append(entry)
    save_json(DATA_DIR / "menus.json", out)


def main() -> int:
    restaurants = load_json(ROOT / "scripts" / "restaurants.json", [])
    state = load_json(STATE_FILE, {})
    jobs = {
        "nl": run_nl,
        "pps": lambda: run_pps(state),
        "hyosung": lambda: run_inbox("hyosung", "아펠가모 반포 구내식당(효성반포빌딩 11층)", state),
    }
    failures = 0
    for rid, job in jobs.items():
        try:
            job()
        except Exception as exc:  # 한 곳이 실패해도 나머지는 계속 갱신
            failures += 1
            traceback.print_exc()
            warn(rid, f"갱신 실패: {exc}")
        finally:
            save_json(STATE_FILE, state)  # 판독 비용이 드는 작업 기록은 바로 저장
    build_index(restaurants)
    print(f"완료 — 실패 {failures}곳")
    return 1 if failures == len(jobs) else 0


if __name__ == "__main__":
    sys.exit(main())
