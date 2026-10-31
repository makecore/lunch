# 오늘의 점심

국립중앙도서관 주변 **세 곳의 구내식당 식단을 날짜별로 비교하는 작은 웹사이트**입니다. 별도 웹 서버나 프런트엔드 빌드 없이 GitHub Pages에서 동작합니다.

**[식단 보기 →](https://makecore.github.io/lunch/)**

| 식당 | 수집 방식 | 필요한 것 |
|---|---|---|
| 국립중앙도서관 | 공식 웹페이지의 식단 표 읽기 | 없음 |
| 서울지방조달청 | 게시판 첨부 이미지를 AI로 판독 | Gemini 또는 Claude API 키 |
| 아펠가모 반포 | `inbox/hyosung/`에 올린 사진 판독 | 사진 + API 키 |

날짜를 눌러 메뉴를 보고, 지난주·다음 주로 이동하거나 **오늘로** 돌아올 수 있습니다. 작은 점은 메뉴가 등록된 날짜입니다. 모바일과 어두운 화면 설정을 지원합니다. 식단 정보가 없다는 뜻과 실제 휴무를 구분해 표시합니다.

## 로컬에서 바로 보기

Python 3.12를 권장합니다. **화면만 확인할 때는 패키지 설치나 API 키가 필요 없습니다.**

```sh
git clone https://github.com/makecore/lunch.git
cd lunch
python3 -m http.server 8000 --directory docs
```

브라우저에서 <http://localhost:8000>을 엽니다. `index.html`을 직접 더블클릭하면 브라우저가 JSON 읽기를 차단할 수 있으므로 위 서버로 실행하세요.

## 수집 코드 실행 및 테스트

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

```sh
# 저장된 식당별 JSON을 menus.json으로 합치기: 네트워크·AI 호출 없음
python scripts/update.py --build-only

# 공식 사이트 수집 + 새 사진 판독 + 메뉴 파일 갱신
python scripts/update.py
```

전체 갱신은 `docs/data`, `docs/images`, `state/processed.json`을 변경합니다. 키가 없으면 도서관 식단은 수집하고, 조달청은 원본 이미지만 저장합니다. 사진 판독이 필요하면 환경 변수에 API 키를 설정하세요. 키를 파일이나 Git 커밋에 넣지 마세요.

## 자동 수집과 배포 설정

1. 저장소 **Settings → Pages → Source**를 **GitHub Actions**로 설정합니다.
2. **Settings → Secrets and variables → Actions**에 `GEMINI_API_KEY` 또는 `ANTHROPIC_API_KEY`를 Secret으로 등록합니다. 키는 각 제공업체에서 발급합니다.
3. **Actions → 식단 갱신 → Run workflow**를 실행합니다.
4. 배포 완료 후 `https://<계정>.github.io/lunch/`에서 확인합니다.

한국 시간 **06:17, 10:47**에 갱신하도록 예약되어 있습니다. GitHub 예약 작업은 지연될 수 있습니다. `main`의 `inbox`, `docs`, `scripts`, 의존성 또는 워크플로 변경도 갱신을 시작합니다. PR에서는 외부 서비스 호출 없이 파서·검증 테스트와 JavaScript 문법을 점검합니다.

| 설정 | 위치 | 동작 |
|---|---|---|
| `GEMINI_API_KEY` | Secret | Gemini 판독 활성화, 두 키가 있으면 기본 선택 |
| `ANTHROPIC_API_KEY` | Secret | Claude 판독 활성화 |
| `OCR_PROVIDER` | Variable | `gemini` 또는 `claude`; 선택한 키가 없으면 사용 가능한 키로 대체 |
| `OCR_MODEL` | Variable | 계정에서 사용 가능한 모델 ID로 기본 모델 재정의 |

기본 모델 값은 `scripts/ocr.py`의 `DEFAULT_MODELS`에 있습니다. 모델 이용 가능 여부·요금·무료 할당량은 제공업체와 계정에 따라 다릅니다. 모델 오류가 나면 사용 가능한 모델 ID를 `OCR_MODEL`에 지정하세요. 이미지에는 개인정보가 없는 공개 식단표를 사용하세요.

## 사진 등록과 식단 수정

**사진 올리기:** 저장소의 `inbox/hyosung`에서 **Add file → Upload files**로 사진을 올리고 커밋합니다. JPG·PNG·WebP·GIF·HEIC·HEIF를 지원합니다. 글자와 날짜가 선명하게 보이도록 찍어 주세요. API 키가 없으면 이 폴더의 사진은 판독하지 않습니다.

**메뉴 고치기:** `docs/data/pps.json` 또는 `docs/data/hyosung.json`의 `days`에서 해당 날짜의 메뉴를 수정합니다. 커밋하면 자동으로 `menus.json`을 다시 만들고 배포합니다. 로컬에서는 수정 후 `--build-only`를 실행합니다. 도서관 데이터(`nl.json`)는 다음 수집에서 덮어쓰므로 원본 파서 수정이 필요합니다.

**다시 판독하기:** `state/processed.json`에서 해당 이미지 기록을 제거하고 갱신합니다. API 호출 비용이 다시 발생할 수 있으며, 그 이미지에 해당하는 날짜의 수동 수정 내용도 덮어씁니다.

## 어떤 코드가 필요한가

| 위치 | 역할 / 유지 이유 |
|---|---|
| `docs/index.html` | 화면 구조, 접근성, 로딩 안내 |
| `docs/styles.css` | 반응형 화면과 밝은/어두운 색상 |
| `docs/app.js` | 날짜 선택, 식당 카드, 원본 링크, 오류 재시도 |
| `scripts/update.py` | 수집 순서·실패 격리·메뉴 통합, `--build-only` |
| `scripts/source_nl.py`, `source_pps.py` | 서로 다른 공식 사이트 형식 처리 |
| `scripts/ocr.py` | 이미지 판독, 재시도, 결과 검증, 두 판독의 비교 |
| `scripts/common.py` | 날짜·메뉴 분리·JSON 저장 공통 함수 |
| `scripts/restaurants.json` | 식당 표시 정보와 판독 힌트 |
| `docs/data/{nl,pps,hyosung}.json` | 식당별 저장 데이터; 수집 실패 시에도 이전 메뉴 유지 |
| `docs/data/menus.json` | 웹에서 한 번의 요청으로 읽는 통합 결과 |
| `docs/images/`, `state/processed.json` | 원본 대조 및 중복 판독 비용 방지 |
| `tests/`, `.github/workflows/` | 회귀 검사와 자동 수집·배포 |

**정리한 부분:** 외부 글꼴 요청 두 종류, 화면에 쓰이지 않는 스타일, 사용되지 않는 판독 함수 인자, 미사용 `window.__MENUS__` 주입 분기를 제거했습니다. 한 HTML에 섞인 스타일과 동작을 분리했습니다. 프런트엔드 프레임워크나 빌드 도구는 추가하지 않았습니다.

Claude·HEIC 지원과 도서관의 보조 파서는 실제 대체 경로이므로 유지했습니다. 식당별 JSON과 통합 JSON도 각각 수집·수정과 화면 읽기라는 역할이 있어 단순 중복이 아닙니다. 식당을 추가하려면 설정 파일뿐 아니라 `update.py`의 수집 작업도 등록해야 합니다.

## 정확도와 실패 처리

- 이미지를 독립적으로 두 번 읽습니다. 일치하면 **두 번 읽어 일치**, 차이가 있으면 세 번째 판독 후 해당 날짜에 **원본과 대조해 주세요**를 표시합니다. 일치는 정확성을 보장하지 않습니다.
- 빈 판독, 잘못된 날짜·메뉴 형식은 실패로 처리해 다음 실행에서 다시 시도합니다. 빈 메뉴만으로 휴무를 추정하지 않습니다.
- 재검토에서 새로 바뀐 날짜도 확인 대상으로 표시합니다.
- 한 식당의 수집이 실패해도 다른 식당은 계속 처리합니다. 화면은 수집 실패와 미등록을 구분하며, 이전 메뉴를 보여 주는 경우 안내합니다.
- 날짜별 데이터와 이미지 목록은 42일 기준으로 정리합니다. 실제 이미지 파일과 처리 기록은 자동 삭제하지 않습니다.
- API 호출 한도나 모델 오류는 Actions 로그에서 확인하세요. 도서관 HTML 구조 문제는 로컬 `state/debug/nl.html`로 조사할 수 있으며 이 진단 파일은 커밋하지 않습니다.
