"""파서 점검용 테스트. 실행: python -m pytest -q  (또는 python tests/test_parsers.py)"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import ocr  # noqa: E402
import source_nl  # noqa: E402
import source_pps  # noqa: E402
from common import split_menu  # noqa: E402

NL_HTML = """
<div class="diet"><p class="date">2026년 10월 19일 <em>월</em></p>
<table><caption>식당 식단표 안내(중식, 석식)</caption>
<thead><tr><th scope="col">중식</th><th scope="col">석식</th></tr></thead>
<tbody><tr><td>미운영</td><td>미운영</td></tr></tbody></table>
<p class="date">2026년 10월 20일 <em>화</em></p>
<table><caption>식당 식단표 안내(중식, 석식)</caption>
<thead><tr><th>중식</th><th>석식</th></tr></thead>
<tbody><tr><td>쌀밥, 소고기두부국, 돈육김치볶음, 팝콘치킨데리야끼'S, 콩나물잡채, 깍두기, 그린샐러드</td><td>미운영</td></tr></tbody></table>
<p>2026년 10월 24일 <em>토</em></p>
<table><thead><tr><th>중식</th><th>석식</th></tr></thead>
<tbody><tr><td>쌀밥, (뚝)버섯육개장, 떡갈비조림</td><td>미운영</td></tr></tbody></table></div>
"""

PPS_HTML = """
<table><tbody>
<tr><td>150</td><td class="title"><a href="#none" onclick="view('1')">식단표(10.19. ~ 10.23.)</a></td>
<td><a href="/common/fileDown.do;jsessionid=abc!-123?key=202610160013&amp;sn=1"><img alt="첨부파일 다운로드(png)"></a></td>
<td>안병일</td><td>2026-10-16</td><td>1224</td></tr>
<tr><td>149</td><td><a href="#none">식단표(10.12. ~ 10.16.)</a></td>
<td><a href="/common/fileDown.do?key=202610080013&sn=1">첨부</a></td><td>안병일</td><td>2026-10-08</td><td>1504</td></tr>
<tr><td>1</td><td><a href="#none">식단표(12.29. ~ 1.2.)</a></td>
<td><a href="/common/fileDown.do?key=202612260001&sn=1">첨부</a></td><td>안병일</td><td>2026-12-26</td><td>1</td></tr>
</tbody></table>
"""


def test_split_menu_keeps_parentheses():
    assert split_menu("쌀밥, 제육(돼지, 국내산), 김치") == ["쌀밥", "제육(돼지, 국내산)", "김치"]


def test_nl_parse():
    days = source_nl.parse(NL_HTML)
    assert set(days) == {"2026-10-19", "2026-10-20", "2026-10-24"}
    assert days["2026-10-19"][0] == {"label": "중식", "items": [], "closed": True}
    lunch = days["2026-10-20"][0]
    assert lunch["label"] == "중식" and lunch["items"][1] == "소고기두부국" and len(lunch["items"]) == 7
    assert days["2026-10-20"][1]["closed"] is True
    assert days["2026-10-24"][0]["items"][1] == "(뚝)버섯육개장"


def test_nl_parse_text_fallback():
    html = "<div>2026년 10월 21일 수<br>중식<br>석식<br>쌀밥, 가츠동<br>미운영</div>"
    days = source_nl.parse(html)
    assert days["2026-10-21"][0]["items"] == ["쌀밥", "가츠동"]


def test_pps_parse_list():
    posts = source_pps.parse_list(PPS_HTML)
    assert posts[0]["key"] == "202610160013"
    assert posts[0]["week_start"] == "2026-10-19" and posts[0]["week_end"] == "2026-10-23"
    assert "jsessionid" not in posts[0]["file_url"]
    assert posts[0]["file_url"] == "https://www.pps.go.kr/common/fileDown.do?key=202610160013&sn=1"
    assert posts[2]["week_start"] == "2026-12-29" and posts[2]["week_end"] == "2027-01-02"


def test_ocr_diff():
    a = ocr._normalize({"days": {"2026-10-20": [{"label": "중식", "items": ["쌀밥", "된장국"]}]}})
    b = ocr._normalize({"days": {"2026-10-20": [{"label": "중식", "items": ["쌀밥", "된장 국"]}]}})
    c = ocr._normalize({"days": {"2026-10-20": [{"label": "중식", "items": ["쌀밥", "미역국"]}]}})
    assert ocr.diff(a, b) == []
    assert ocr.diff(a, c) == ["2026-10-20 중식"]


class _FakeResp:
    def __init__(self, status, payload):
        self.status_code, self._payload, self.text = status, payload, json.dumps(payload)

    def json(self):
        return self._payload


def test_provider_selection():
    import os
    saved = {k: os.environ.pop(k, None) for k in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OCR_PROVIDER", "OCR_MODEL")}
    try:
        assert ocr.provider() is None and not ocr.available()
        os.environ["ANTHROPIC_API_KEY"] = "a"
        assert ocr.provider() == "claude"
        os.environ["GEMINI_API_KEY"] = "g"
        assert ocr.provider() == "gemini" and ocr.model_name() == "gemini-flash-latest"
        os.environ["OCR_PROVIDER"] = "claude"
        assert ocr.provider() == "claude"
    finally:
        for k, v in saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v


def test_gemini_call_parses_json_and_retries():
    import os
    import requests
    calls = []
    answer = {"week": "11.2.~11.6.", "days": {"2026-11-02": [{"label": "중식 한식", "items": ["쌀밥/흑미밥"]}]}, "notes": ""}
    replies = [
        _FakeResp(429, {"error": {"status": "RESOURCE_EXHAUSTED", "message": "quota",
                                  "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "0s"}]}}),
        _FakeResp(200, {"candidates": [{"content": {"parts": [
            {"text": "생각 중", "thought": True}, {"text": json.dumps(answer, ensure_ascii=False)}]}}]}),
    ]

    def fake_post(self, url, headers=None, json=None, timeout=None):
        calls.append((url, headers, json))
        return replies.pop(0)

    saved_env = {k: os.environ.pop(k, None) for k in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OCR_PROVIDER", "OCR_MODEL")}
    orig_post, orig_sleep, orig_gap = requests.Session.post, ocr.time.sleep, ocr.GEMINI_GAP
    os.environ["GEMINI_API_KEY"] = "test-key"
    requests.Session.post, ocr.time.sleep, ocr.GEMINI_GAP = fake_post, (lambda s: None), 0
    try:
        out = ocr._ask("aGVsbG8=", "image/png", "판독")
    finally:
        requests.Session.post, ocr.time.sleep, ocr.GEMINI_GAP = orig_post, orig_sleep, orig_gap
        for k, v in saved_env.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
    assert len(calls) == 2
    url, headers, body = calls[1]
    assert url.endswith("/models/gemini-flash-latest:generateContent")
    assert headers == {"x-goog-api-key": "test-key"} and "test-key" not in url
    assert body["contents"][0]["parts"][0]["inline_data"]["mime_type"] == "image/png"
    assert out["days"]["2026-11-02"][0]["items"] == ["쌀밥/흑미밥"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("통과:", name)
