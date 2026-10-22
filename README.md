# 반포 구내식당 식단 (lunch)

반포대로 근처 구내식당 세 곳의 식단을 **매일 아침 자동으로 모아** 한 페이지로 보여 주는 저장소(repository)입니다.

| 식당 | 식단이 올라오는 방식 | 이 저장소가 읽는 방법 |
|---|---|---|
| 국립중앙도서관 구내식당 | 누리집에 글자(표)로 게시 | 매일 페이지를 읽어 그대로 옮김 |
| 서울지방조달청 구내식당 | 게시판에 주간 식단표 **이미지** 첨부 | 새 글이 올라온 주에만 AI가 이미지를 판독 |
| 아펠가모 반포 구내식당 (효성반포빌딩 11층) | 게시 위치 확인 중 | 사람이 식단표 사진을 `inbox/hyosung`에 올리면 AI가 판독 |

## 어떻게 돌아가나

```
매일 06:17, 10:47 (한국 시간)
        │
        ▼
GitHub Actions(깃허브가 대신 돌려 주는 자동 실행 기능)
        │
        ├─ 국립중앙도서관 페이지 읽기 ───────────────┐
        ├─ 조달청 게시판 확인 → 새 이미지면 AI 판독 ─┤→ docs/data/menus.json 저장
        └─ inbox 폴더에 새 사진이면 AI 판독 ─────────┘
        │
        ▼
GitHub Pages(무료 웹페이지)로 공개 → 휴대폰에서 바로 확인
```

**이미지 판독의 정확도를 높이는 장치**
1. 같은 이미지를 AI가 **서로 따로 두 번** 읽고 결과를 비교합니다.
2. 두 결과가 같으면 화면에 `두 번 읽어 일치`로 표시합니다.
3. 다르면 AI가 이미지를 다시 보고 엇갈린 칸만 바로잡은 뒤, 화면에 `확인 필요`로 표시합니다.
4. 어느 경우든 **원본 식단표 이미지 링크**를 함께 보여 줘서 바로 대조할 수 있습니다.
5. 이미 판독한 이미지는 `state/processed.json`에 기록해 두고 다시 판독하지 않습니다(주 1회만 비용 발생).

## 처음 한 번만 하는 설정

### 1. API 키 등록 (이미지 판독용)
- API 키(API key)란 프로그램이 Claude AI를 쓸 수 있게 해 주는 비밀 열쇠입니다.
- https://console.anthropic.com 에서 키를 만든 뒤,
- 저장소 화면 → **Settings → Secrets and variables → Actions → New repository secret**
  - Name: `ANTHROPIC_API_KEY`
  - Secret: 복사한 키 붙여넣기
- 키가 없어도 국립중앙도서관 식단은 정상 표시됩니다. 조달청은 원본 이미지 링크만 표시됩니다.

### 2. 웹페이지 켜기
- **Settings → Pages → Build and deployment → Source** 를 `GitHub Actions` 로 선택

### 3. 첫 실행
- **Actions** 탭 → 왼쪽 `식단 갱신` → 오른쪽 `Run workflow` 버튼
- 2~3분 뒤 `https://<내 아이디>.github.io/lunch/` 에서 확인

## 효성반포빌딩 식단 사진 올리는 법 (아이폰)
1. 식단표를 사진으로 찍습니다(글자가 화면에 꽉 차게, 빛 반사 없이).
2. 깃허브 웹사이트에서 이 저장소 → `inbox` → `hyosung` 폴더로 이동
3. `Add file` → `Upload files` → 사진 선택 → `Commit changes`
4. 사진을 올리면 자동 실행이 바로 시작되고, 몇 분 뒤 페이지에 반영됩니다. (HEIC 사진도 됩니다)

## 판독이 틀렸을 때 고치는 법
`docs/data/pps.json`(조달청) 또는 `docs/data/hyosung.json`(효성)에서 해당 날짜의 메뉴 글자를 직접 고치고 저장(Commit)하면 됩니다. 이미 판독한 이미지는 다시 판독하지 않으므로 고친 내용이 유지됩니다.

## 파일 구성
| 위치 | 하는 일 |
|---|---|
| `scripts/update.py` | 전체 실행 순서(수집 → 판독 → 페이지 데이터 생성) |
| `scripts/source_nl.py` | 국립중앙도서관 식단 읽기 |
| `scripts/source_pps.py` | 조달청 게시판에서 식단표 이미지 찾기·내려받기 |
| `scripts/ocr.py` | AI 이미지 판독과 두 번 읽기 교차검증 |
| `scripts/restaurants.json` | 식당 이름·위치·안내 문구 (식당 추가 시 여기 수정) |
| `docs/index.html` | 휴대폰용 식단 페이지 |
| `docs/data/*.json` | 식당별 식단 데이터 |
| `.github/workflows/update-menus.yml` | 자동 실행 일정 |
| `tests/test_parsers.py` | 읽기 기능 점검용 테스트 |

## 참고
- 판독 모델은 기본 `claude-sonnet-5-5`입니다(월 약 1,000원 수준). 바꾸려면 Settings → Variables에 `OCR_MODEL`을 추가하세요.
- 식당 누리집 구조가 바뀌면 Actions 실행 기록에 노란 경고가 남고, 페이지의 해당 식당 칸에도 안내가 표시됩니다.
