"""식단표 이미지 판독 (Claude 비전 모델 사용).

정확도를 위해 같은 이미지를 서로 독립적으로 두 번 읽고 결과를 비교한다.
  - 두 결과가 같으면 → '교차검증 일치'
  - 다르면 → 세 번째로 이미지와 두 결과를 함께 주고 다른 부분만 다시 확인시켜 최종본을 만들고,
    어떤 항목이 엇갈렸는지 기록해 화면에 '확인 필요'로 표시한다.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re

MODEL = os.environ.get("OCR_MODEL", "claude-sonnet-5-5")
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


def _client():
    import anthropic  # 필요할 때만 불러온다

    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    return anthropic.Anthropic(api_key=key)


def available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


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


def _ask(client, image_b64: str, media_type: str, prompt: str) -> dict:
    msg = client.messages.create(
        model=MODEL,
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
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    return _normalize(_extract_json(text))


def _normalize(result: dict) -> dict:
    days = {}
    for date, meals in (result.get("days") or {}).items():
        clean = []
        for m in meals or []:
            items = [re.sub(r"\s+", " ", str(i)).strip() for i in (m.get("items") or [])]
            items = [i for i in items if i]
            clean.append({"label": str(m.get("label", "")).strip() or "식사",
                          "items": items,
                          "closed": bool(m.get("closed")) or not items})
        days[str(date)] = clean
    return {"week": result.get("week", ""), "days": days, "notes": result.get("notes", "")}


def _flat(result: dict) -> dict[tuple[str, str], tuple[str, ...]]:
    """비교하기 쉽게 (날짜, 끼니) → 메뉴 목록 형태로 편다. 띄어쓰기 차이는 무시한다."""
    out = {}
    for date, meals in result["days"].items():
        for m in meals:
            out[(date, m["label"].replace(" ", ""))] = tuple(i.replace(" ", "") for i in m["items"])
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
    client = _client()
    if client is None:
        raise RuntimeError("ANTHROPIC_API_KEY가 설정되지 않아 이미지를 판독할 수 없습니다.")

    data, media_type = _prepare_image(data, media_type)
    b64 = base64.standard_b64encode(data).decode()
    base_prompt = f"이 이미지는 구내식당 주간 식단표다.\n\n기준 정보: {context}\n\n{RULES}\n\n{SCHEMA_HINT}"

    first = _ask(client, b64, media_type, base_prompt)
    second = _ask(client, b64, media_type, base_prompt + "\n\n표를 왼쪽 위부터 한 칸씩 차례로 확인하며 옮겨라.")
    disputed = diff(first, second)
    if not disputed:
        first.update(verified=True, disputed=[], model=MODEL)
        return first

    review_prompt = (
        f"{base_prompt}\n\n"
        "같은 이미지를 두 번 판독했더니 아래 칸들의 결과가 서로 달랐다.\n"
        f"엇갈린 칸: {', '.join(disputed)}\n\n"
        f"판독 A:\n{json.dumps(first, ensure_ascii=False)}\n\n"
        f"판독 B:\n{json.dumps(second, ensure_ascii=False)}\n\n"
        "이미지를 다시 자세히 보고, 엇갈린 칸은 이미지에 실제로 적힌 대로 바로잡아 전체 최종본을 위 형식으로 출력하라."
    )
    final = _ask(client, b64, media_type, review_prompt)
    final.update(verified=False, disputed=disputed, model=MODEL)
    return final
