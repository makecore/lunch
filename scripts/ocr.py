"""식단표 이미지 판독 (AI 비전 모델 사용).

판독에 쓰는 AI는 GitHub 저장소 Secrets에 등록된 키에 따라 정해진다.
  - GEMINI_API_KEY 가 있으면 → Google Gemini (무료 등급 사용 가능, 기본값)
  - 없고 ANTHROPIC_API_KEY 가 있으면 → Anthropic Claude
  - 둘 다 있으면 Gemini를 쓴다. 바꾸려면 Variables에 OCR_PROVIDER=claude 를 넣는다.

정확도를 위해 같은 이미지를 서로 독립적으로 두 번 읽고 결과를 비교한다.
  - 두 결과가 같으면 → '교차검증 일치'
  - 다르면 → 세 번째로 이미지와 두 결과를 함께 주고 다른 부분만 다시 확인시켜 최종본을 만들고,
    어떤 항목이 엇갈렸는지 기록해 화면에 '확인 필요'로 표시한다.
"""
from __future__ import annotations

import datetime as dt
import base64
import io
import json
import os
import re
import time

DEFAULT_MODELS = {
    "gemini": "gemini-flash-latest",  # 항상 최신 Flash 모델을 가리키는 별칭(무료 등급 대상)
    "claude": "claude-sonnet-5-5",
}
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta"
MAX_BYTES = 4_500_000  # API 이미지 한도(5MB)보다 조금 작게

SCHEMA_HINT = """출력은 아래 JSON 하나만 쓴다. 설명 문장, 코드블록 표시는 쓰지 않는다.
{
  "week": "이미지에 적힌 기간 문구 그대로 (없으면 빈 문자열)",
  "days": {
    "YYYY-MM-DD": [
      {"label": "중식", "items": ["메뉴1", "메뉴2"], "closed": false}
    ]
  },
  "notes": "가격·운영시간·안내문 등 메뉴 외 문구 (없으면 빈 문자열)"
}"""

RULES = """판독 규칙:
1. 이미지에 적힌 글자를 그대로 옮긴다. 맞춤법을 고치거나, 비슷한 다른 음식으로 바꾸거나, 추측해서 채우지 않는다.
2. 메뉴 하나가 한 줄에 하나씩 적혀 있으면 한 줄을 항목 하나로 본다. 괄호 안 원산지·부가 표기도 그대로 둔다.
3. 날짜는 반드시 YYYY-MM-DD로 쓴다. 연도가 이미지에 없으면 제공된 '기준 정보'의 연도를 쓴다.
4. 끼니 이름(조식·중식·석식, A코너·B코너, 일품 등)은 이미지 표기를 따라 label에 넣는다.
   코너가 나뉘어 있으면 "중식 A", "중식 B"처럼 끼니와 코너를 함께 쓴다.
5. '휴무', '미운영', '공휴일'처럼 운영하지 않는 칸은 items를 []로, closed를 true로 쓴다.
6. 열량(kcal)·영양소 숫자는 items에 넣지 않는다.
7. 흐리거나 잘려서 읽을 수 없는 글자는 '?'로 남긴다. 절대 지어내지 않는다."""


def provider() -> str | None:
    """사용할 AI 이름('gemini' 또는 'claude'). 쓸 수 있는 키가 없으면 None."""
    keys = {"gemini": os.environ.get("GEMINI_API_KEY"), "claude": os.environ.get("ANTHROPIC_API_KEY")}
    wanted = (os.environ.get("OCR_PROVIDER") or "").strip().lower()
    if wanted in keys and keys[wanted]:
        return wanted
    for name in ("gemini", "claude"):
        if keys[name]:
            return name
    return None


def model_name(name: str | None = None) -> str:
    name = name or provider() or "gemini"
    return (os.environ.get("OCR_MODEL") or "").strip() or DEFAULT_MODELS[name]


def available() -> bool:
    return provider() is not None


def _prepare_image(data: bytes, media_type: str) -> tuple[bytes, str]:
    """너무 큰 이미지는 화질을 유지하며 용량만 줄인다."""
    if len(data) <= MAX_BYTES:
        return data, media_type
    from PIL import Image

    img = Image.open(io.BytesIO(data)).convert("RGB")
    for quality in (92, 85, 78):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=quality)
        if buf.tell() <= MAX_BYTES:
            return buf.getvalue(), "image/jpeg"
        img = img.resize((int(img.width * 0.85), int(img.height * 0.85)))
    return buf.getvalue(), "image/jpeg"


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start : end + 1])


# ---------- Claude ----------

def _ask_claude(image_b64: str, media_type: str, prompt: str) -> str:
    import anthropic  # 필요할 때만 불러온다

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = client.messages.create(
        model=model_name("claude"),
        max_tokens=8000,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    )
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


# ---------- Gemini ----------

_gemini_model: str | None = None   # 실제로 호출에 성공한 모델 이름(대체 모델로 바뀌었을 수 있음)
_last_call = 0.0
GEMINI_GAP = float(os.environ.get("GEMINI_GAP_SECONDS", "6"))  # 무료 등급 분당 호출 제한을 피하는 간격


def _gemini_error(resp) -> str:
    try:
        err = resp.json().get("error", {})
        return f"{resp.status_code} {err.get('status', '')}: {err.get('message', '')[:300]}"
    except ValueError:
        return f"{resp.status_code}: {resp.text[:300]}"


def _retry_seconds(resp, attempt: int) -> float:
    """429(호출 한도 초과) 응답에 적힌 대기 시간을 읽는다. 없으면 점점 길게 기다린다."""
    try:
        for d in resp.json().get("error", {}).get("details", []):
            if str(d.get("@type", "")).endswith("RetryInfo"):
                return min(float(str(d.get("retryDelay", "0s")).rstrip("s")) + 1, 90)
    except (ValueError, TypeError):
        pass
    return 15 * (attempt + 1)


def _pick_gemini_fallback(session, key: str) -> str | None:
    """기본 별칭이 없어졌을 때, 계정에서 쓸 수 있는 Flash 모델 중 하나를 고른다."""
    resp = session.get(f"{GEMINI_URL}/models", headers={"x-goog-api-key": key},
                       params={"pageSize": 1000}, timeout=30)
    if resp.status_code != 200:
        return None
    names = []
    for m in resp.json().get("models", []):
        name = m.get("name", "").removeprefix("models/")
        if "generateContent" not in m.get("supportedGenerationMethods", []):
            continue
        if "flash" not in name or re.search(r"lite|image|tts|live|audio|embed|thinking", name):
            continue
        names.append(name)
    if not names:
        return None
    # 이름에 latest가 붙은 별칭 → 숫자가 큰(최신) 순서로 고른다.
    names.sort(key=lambda n: ("latest" in n, [int(x) for x in re.findall(r"\d+", n)]), reverse=True)
    return names[0]


def _ask_gemini(image_b64: str, media_type: str, prompt: str) -> str:
    import requests

    global _gemini_model, _last_call
    key = os.environ["GEMINI_API_KEY"]
    session = requests.Session()
    model = _gemini_model or model_name("gemini")
    body = {
        "contents": [{"role": "user", "parts": [
            {"inline_data": {"mime_type": media_type, "data": image_b64}},
            {"text": prompt},
        ]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }
    tried_fallback = False
    for attempt in range(5):
        wait = GEMINI_GAP - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()
        resp = session.post(f"{GEMINI_URL}/models/{model}:generateContent",
                            headers={"x-goog-api-key": key}, json=body, timeout=180)
        if resp.status_code == 200:
            _gemini_model = model
            data = resp.json()
            cands = data.get("candidates") or []
            if not cands:
                raise RuntimeError(f"Gemini가 답을 주지 않았습니다: {data.get('promptFeedback', {})}")
            parts = (cands[0].get("content") or {}).get("parts") or []
            text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
            if not text.strip():
                raise RuntimeError(f"Gemini 응답이 비어 있습니다 (finishReason={cands[0].get('finishReason')})")
            return text
        if resp.status_code == 404 and not tried_fallback and not os.environ.get("OCR_MODEL"):
            tried_fallback = True
            alt = _pick_gemini_fallback(session, key)
            if alt and alt != model:
                print(f"::notice::Gemini 모델 '{model}'을 찾지 못해 '{alt}'로 바꿔 판독합니다.")
                model = alt
                continue
        if resp.status_code in (429, 500, 502, 503, 504) and attempt < 4:
            delay = _retry_seconds(resp, attempt) if resp.status_code == 429 else 10 * (attempt + 1)
            print(f"Gemini {resp.status_code} — {delay:.0f}초 기다린 뒤 다시 시도합니다.")
            time.sleep(delay)
            continue
        raise RuntimeError(f"Gemini 호출 실패 ({model}) — {_gemini_error(resp)}")
    raise RuntimeError(f"Gemini 호출 실패 ({model}) — 여러 번 다시 시도했지만 응답이 없습니다.")


def _ask(image_b64: str, media_type: str, prompt: str) -> dict:
    ask = _ask_gemini if provider() == "gemini" else _ask_claude
    return _normalize(_extract_json(ask(image_b64, media_type, prompt)))


def _used_model() -> str:
    if provider() == "gemini":
        return _gemini_model or model_name("gemini")
    return model_name("claude")


def _normalize(result: dict) -> dict:
    if not isinstance(result, dict) or not isinstance(result.get("days"), dict) or not result["days"]:
        raise ValueError("판독 결과에 날짜별 식단이 없습니다.")
    days = {}
    for date, meals in result["days"].items():
        if not isinstance(date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            raise ValueError(f"잘못된 식단 날짜: {date}")
        dt.date.fromisoformat(date)
        if not isinstance(meals, list) or not meals:
            raise ValueError(f"{date}: 끼니 정보가 없습니다.")
        clean = []
        for m in meals:
            if not isinstance(m, dict) or not isinstance(m.get("items", []), list):
                raise ValueError(f"{date}: 메뉴 목록 형식이 잘못되었습니다.")
            if not isinstance(m.get("closed", False), bool):
                raise ValueError(f"{date}: 휴무 여부는 true 또는 false여야 합니다.")
            if any(not isinstance(item, str) for item in m.get("items", [])):
                raise ValueError(f"{date}: 메뉴는 문자열이어야 합니다.")
            items = [re.sub(r"\s+", " ", str(i)).strip() for i in (m.get("items") or [])]
            items = [i for i in items if i]
            clean.append({"label": str(m.get("label", "")).strip() or "식사",
                          "items": items,
                          "closed": m.get("closed", False)})
        days[str(date)] = clean
    return {"week": result.get("week", ""), "days": days, "notes": result.get("notes", "")}


def _flat(result: dict) -> dict[tuple[str, str], tuple[bool, tuple[str, ...]]]:
    """비교하기 쉽게 (날짜, 끼니) → 메뉴 목록 형태로 편다. 띄어쓰기 차이는 무시한다."""
    out = {}
    for date, meals in result["days"].items():
        for m in meals:
            out[(date, m["label"].replace(" ", ""))] = (m["closed"], tuple(i.replace(" ", "") for i in m["items"]))
    return out


def diff(a: dict, b: dict) -> list[str]:
    fa, fb = _flat(a), _flat(b)
    problems = []
    for key in sorted(set(fa) | set(fb)):
        if fa.get(key) != fb.get(key):
            problems.append(f"{key[0]} {key[1]}")
    return problems


def transcribe(data: bytes, media_type: str, context: str) -> dict:
    """이미지 → 식단 JSON. 반환값에 verified(교차검증 결과)와 disputed(엇갈린 칸)를 붙인다."""
    if not available():
        raise RuntimeError("GEMINI_API_KEY(또는 ANTHROPIC_API_KEY)가 설정되지 않아 이미지를 판독할 수 없습니다.")

    data, media_type = _prepare_image(data, media_type)
    b64 = base64.standard_b64encode(data).decode()
    base_prompt = f"이 이미지는 구내식당 주간 식단표다.\n\n기준 정보: {context}\n\n{RULES}\n\n{SCHEMA_HINT}"

    first = _ask(b64, media_type, base_prompt)
    second = _ask(b64, media_type, base_prompt + "\n\n표를 왼쪽 위부터 한 칸씩 차례로 확인하며 옮겨라.")
    disputed = diff(first, second)
    if not disputed:
        first.update(verified=True, disputed=[], model=_used_model())
        return first

    review_prompt = (
        f"{base_prompt}\n\n"
        "같은 이미지를 두 번 판독했더니 아래 칸들의 결과가 서로 달랐다.\n"
        f"엇갈린 칸: {', '.join(disputed)}\n\n"
        f"판독 A:\n{json.dumps(first, ensure_ascii=False)}\n\n"
        f"판독 B:\n{json.dumps(second, ensure_ascii=False)}\n\n"
        "이미지를 다시 자세히 보고, 엇갈린 칸은 이미지에 실제로 적힌 대로 바로잡아 전체 최종본을 위 형식으로 출력하라."
    )
    final = _ask(b64, media_type, review_prompt)
    disputed = sorted(set(disputed + diff(first, final) + diff(second, final)))
    final.update(verified=False, disputed=disputed, model=_used_model())
    return final
