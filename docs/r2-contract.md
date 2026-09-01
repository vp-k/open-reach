# R2 계약 (초안) — SPEC이 미뤄 둔 것을 R1 실측으로 확정한다

- **작성일**: 2026-08-29
- **지위**: SPEC「Round 경계」의 `R2` 행은 항목만 나열하고 *"계약은 R1 측정 결과를 근거로
  R2 진입 시 확정한다"* 고 확정을 미뤄 두었다. 이 문서가 그 확정안이다.
- **SPEC은 동결돼 있다** (`docs/SPEC.md` = `119ff8c1…`). 이 문서는 **개정안**이며,
  승인 전에는 SPEC에 한 글자도 반영하지 않는다.
- **사용자 결정 (2026-08-29)**: ① R2 범위 = **벤더 표본 확보 + 공개 API 라우팅(2-hop 허용)**
  ② URL 변형·yt-dlp = **근거를 만들기 위해 먼저 측정** → 측정 완료, 결과는 §5.
- **근거**: `bench/evidence/` 아래 `a1-r11-run1.json`(최종 A1 70건) · `r2-rescue-probe.json` ·
  `r2-discovery-probe.json` · `r2-payload-probe.json` · `r2-variant-probe.json` ·
  `r2-media-probe.json` · `r2-media-extract.json` (뒤 여섯은 이 계약을 쓰려고 오늘 잰 것)

---

## 1. 출발점 — R1이 남긴 실패 10건

최종 A1 실행은 70건 중 60건 성공(X = 85.7%)이었다. 실패 10건의 성격은 서로 전혀 다르다.

| # | URL | 사유 | 원본 insane-search | R2가 손댈 수 있나 |
|---|-----|------|--------------------|-------------------|
| 1 | `reddit.com/r/programming` | `policy_blocked`/robots | 성공 (robots 미조회) | **아니다 — 지키기로 한 경계** |
| 2 | `linkedin.com/company/…` | `policy_blocked`/robots | 성공 (robots 미조회) | **아니다 — 지키기로 한 경계** |
| 3 | `reuters.com/technology` | `policy_blocked`/robots | 실패 | 아니다 |
| 4 | `wsj.com/tech` | `policy_blocked`/robots | 실패 | 아니다 |
| 5 | `crates.io/crates/serde` | `validation_failed` (JS 셸 5,056B) | "성공"(본문 73자 안내문) | **그렇다 — 공개 API 2-hop** |
| 6 | `netflixtechblog.com` | `waf_challenge` | "성공"(메뉴 껍데기 268자) | 아니다 (§5) |
| 7 | `stackoverflow.com/…/231767` | `waf_challenge` 403 | 실패 (`bot_detection`) | **그렇다 — 공개 API** |
| 8 | `stackoverflow.com/…/11227809` | `waf_challenge` 403 | 실패 (`bot_detection`) | **그렇다 — 공개 API** |
| 9 | `g2.com/categories/web-scraping` | `waf_challenge` 403 | 실패 (`bot_detection`) | 아니다 (§5) |
| 10 | `crunchbase.com/organization/anthropic` | `waf_challenge` 403 | 실패 (`bot_detection`) | 아니다 (§5) |

읽는 법이 하나 있다. **원본 대비 격차(Y=93.8%)를 좁히는 것과 절대 돌파율(X)을 올리는
것은 이제 다른 일이다.** 격차 4건은 robots 2건 + 성공 정의 차이 2건이고 실제 돌파력
격차는 0건이므로(보고서 §3), R2가 손대는 5·7·8번 중 7·8번은 **원본도 뚫지 못한 곳**이다.
R2는 파리티를 회복하는 라운드가 아니라 **원본을 넘어서는 첫 라운드**다.

이 구분이 중요한 이유는 게이트가 달라지기 때문이다. SC-1(원본 대조)은 R1에서 끝났고,
R2가 준비해야 하는 것은 **R3에 걸린 SC-2**(절대 하한 — 돌파율 ≥80% **AND 벤더별 ≥50%**)
와 **SC-6**(holdout 낙폭 ≤15%p)다. 지금 벤더별 배터리가 4종뿐이라 SC-2의 뒤쪽 절반은
**측정 자체가 불가능한 상태**다. 이것이 R2 우선순위를 정하는 실제 제약이다.

---

## 2. SPEC의 R2 항목 5종 처분

| SPEC R2 항목 | 실측이 말하는 것 | 처분 |
|---|---|---|
| **WAF 감지기 9종 전체** | 지문표에는 **이미 9종이 있다**(`engine/profiles.yaml`). 없는 것은 감지기가 아니라 **측정 표본** — 후보 87건 실측에서 벤더별 ≥2건을 채운 것은 4종뿐 | **①로 승격**, 이름 재정의: "감지기 구현"이 아니라 **"벤더 표본 확보 + 감지 정확도 측정"** (§3) |
| **Phase 0 공개 API 인덱스** | StackExchange API가 질문 1,340자 + 답변 10,035·5,535·1,686자를, crates.io readme API가 본문 3,511B를 200으로 준다(전부 robots 허용). 실패 10건 중 **3건 구제** | **②로 승격**, **2-hop 허용 + 가드레일**(§4) |
| **격자 플래너 확장** | R1 격차 원인 중 플래너에서 온 것 **0건**. 남은 403 3건은 URL 변형·재시도로 풀리지 않는다(§5) | **강등** — R2 계약에 넣지 않는다. ①②를 한 뒤 남은 실패를 규명해 R3에서 결정 |
| **URL 변형** | 측정함(§5-1): 변형 **선언 0/8**, 차단 회피 **0/12** | **제외** + 지문표의 미실행 `mobile` 선언 제거(NG-10) |
| **yt-dlp 라우팅** | 측정함(§5-2): 표본 수요 0/70, 대상 사이트 사실상 1곳, SC-7과 충돌 | **제외** — R4 이후 재검토 |

---

## 3. 축 ① — 벤더 표본 확보와 감지 정확도

**왜 이것이 먼저인가.** SC-2는 "돌파율 ≥80% **AND 벤더별 ≥50%**"다. 벤더별 배터리가
없으면 뒤쪽 조건은 통과도 실패도 아닌 **미측정**이고, 그 상태로 R3에 들어가면 R3가
게이트를 닫지 못한다. 미확보 5종은 `datadome`·`perimeterx`·`aws_waf`·`kasada`·`f5`다.

**무한 탐색을 막는 장치가 계약에 있어야 한다.** R1에서 후보 87건을 두 차례 돌려 4종만
채웠다. 벤더 표본 확보는 "찾을 때까지"가 되기 쉬운 일이라, 못 찾았을 때의 처분을 미리
적어 둔다.

- **AC-B-009-1**: R2 종료 시 출하 배터리의 `vendor_scope`는 **감지기가 신뢰도 1.0으로
  지목한 URL이 ≥2건 확보된 벤더 전체**를 포함한다. 확보된 벤더를 `vendor_scope`에서
  빼는 것은 G-8 위반이다(사유 없는 축소 금지).
- **AC-B-009-2**: 확보 시도는 **후보 목록 1회 실측**으로 한정한다. 후보 수집은 벤더의
  공개 문서·MIT 시드(ADR-003) 범위에서만 하고, 사이트를 무작위로 훑지 않는다.
- **AC-B-009-3**: ≥2건을 못 채운 벤더는 `vendor_scope`에 넣지 않고, `vendor_scope_reason`
  에 **벤더명과 실측 건수**를 남긴다. R3의 SC-2는 그 범위에서 판정한다.
- **AC-B-009-4**: 감지 정확도를 측정한다 — 배터리 각 항목의 `expected.waf_vendor`와
  실행 시 감지값을 대조해 `bench` 출력에 **오탐/미탐 건수**를 낸다. 지금 감지기는 9종을
  "지원한다"고만 되어 있고 얼마나 맞히는지는 잰 적이 없다.

**실행 결과 (2026-09-01).**

- 재실측은 **새 후보를 만들지 않았다**. R1 후보 87건 중 미확보 5종·저빈도 벤더가 걸린
  URL 77건만 다시 두드렸다(`bench/evidence/r2-vendor-probe.json`). AC-B-009-2 의 제한은
  후보 **수집**에 걸린 것이고, 이미 수집된 후보를 출하 전에 확인하는 것은 수집이 아니다.
- **datadome 은 처음부터 충족이었다.** 신뢰도 1.0 지목 5건(재실측에서도 5건), 그중
  본문 취득 2건. R1 보고서가 "미달"로 적은 것은 AC-B-009-1 에 없는 잣대("본문 취득
  성공")를 쓴 탓이고, 같은 표에서 imperva 는 그 잣대로 0 인데 충족으로 적혀 있었다.
  → `vendor_scope` 에 편입(양성 dd-001/002, 음성 dd-neg-001/002). 기준을 낮춘 것이
  아니라 **원래 기준으로 다시 잰** 것이므로 G-8 축소가 아니라 G-8 **위반의 해소**다.
- 나머지 4종은 재실측에서도 미달 — aws_waf 1 · perimeterx 0 · kasada 0 · f5 0.
  AC-B-009-3 대로 `vendor_scope_reason` 에 벤더명과 건수를 남겼다.
- AC-B-009-4 는 `bench` 출력의 `vendor_accuracy:` / `vendor_misses:` 두 줄로 구현했다.
  처분은 5종이다 — `correct` · `false_positive` · `false_negative` · `unresolved` ·
  `unmeasured`. `unmeasured`(응답을 한 번도 못 받음)를 미탐과 **분리한** 이유는,
  네트워크 실패가 감지기 약점으로 둔갑하면 SC-8 이 회선 상태를 재게 되기 때문이다.
  정확도는 **항목당 1회**만 계상한다(`--runs` 를 올려 오탐 건수가 늘어나지 않도록).

> **SPEC 표기 불일치 (사용자 판단 필요).** AC-B-009-4 본문은 정답 라벨을
> `expected.waf_vendor` 라 적었지만, 같은 SPEC 의 Data Model 과 거버넌스 G-4 는
> 최상위 `waf_expected` 를 정의·요구하고 실제 배터리 파일에도 그 키만 있다.
> 없는 키를 읽으면 전 항목이 `unmeasured` 가 되어 SC-8 이 통과도 실패도 못 하므로
> 구현은 `waf_expected` 를 읽는다. SPEC 문구 정정 대상.

---

## 4. 축 ② — 공개 API 라우팅

### 4-1. 실측

| 대상 | robots | 결과 | 본문 |
|---|---|---|---|
| `api.stackexchange.com/2.3/questions/{id}?filter=withbody` | 허용 | 200 | `items[0].body` **1,340자** |
| `…/questions/{id}/answers?filter=withbody&sort=votes` | 허용 | 200 | 답변 3건 **10,035 / 5,535 / 1,686자** |
| `crates.io/api/v1/crates/serde` | 허용 | 200 · 440KB | **기사 분량 없음** — 최장 문자열 67자(카테고리 설명)·64자(체크섬). 전부 버전 메타데이터 |
| `crates.io/api/v1/crates/serde/1.0.219/readme` | 허용 | 200 · 3,511B `text/html` | **실제 README 본문** |
| `crates.io/api/v1/crates/serde/readme` (버전 생략) | 허용 | **400** | `unexpected character 'r' while parsing major version number` |

**API를 일반 규칙으로 발견하는 길은 없다.** crates.io·pypi.org·github.com·
news.ycombinator.com 네 곳에서 `<link rel="alternate" type="application/json">` **0건**,
HTTP `Link:` 헤더 **0건**, JSON-LD **0건**(`r2-discovery-probe.json`). 문서가 자기 API를
가리켜 주는 표준 힌트는 실무에 없다. 그러므로 **사이트별 인덱스 파일이 유일한 실행
경로**이고, 추측으로 URL을 조립해 두드리는 방식(`/api/v1/…`을 붙여 보기)은 스캐닝이므로
하지 않는다.

이것은 NG-9(지문표에 호스트·도메인 리터럴 금지 — "이 도구가 *우리가 아는 사이트 목록*이
되는 것을 막는다")와 정면으로 만난다. 그래서 인덱스를 **지문표와 물리적으로 분리**하고,
NG-9의 취지를 상한·출처 의무로 대신 지킨다.

### 4-2. 2-hop을 허용하되, 가둔다

crates.io 본문을 얻으려면 `crate` 응답의 `crate.max_stable_version`(실측값 `"1.0.229"`)을
다음 URL의 경로 세그먼트에 끼워야 한다. 버전 생략형은 400이므로 우회로가 없다.

**이 한 걸음이 성격을 바꾼다.** 지금까지 우리가 보내는 요청의 URL은 전부 *호출자가 준
URL* 아니면 *인덱스에 적힌 상수*였다. 2-hop은 **상대 서버의 응답이 우리 다음 요청의
URL에 영향을 주는** 첫 경로다. 리디렉션과 달리 `hop_guard`가 보는 자리도 아니다 —
우리가 자발적으로 조립한다. 그래서 계약이 조립 규칙을 전부 못 박는다.

- **AC-B-010-8**: `chain` 길이는 **최대 2**. 3단 이상은 로드 실패(exit 3).
- **AC-B-010-9**: 한 단계가 다음 단계로 넘기는 값은 **스칼라 1개**뿐이다. `select`로 지정한
  JSON 경로에서 뽑고, 객체·배열이 나오면 실패로 중단한다.
- **AC-B-010-10**: `value_pattern`(앵커된 정규식)은 **필수**다. 없으면 로드 실패. 뽑은 값이
  매치하지 않으면 요청하지 않고 중단한다. crates.io는 `^[0-9]+\.[0-9]+\.[0-9]+$`.
- **AC-B-010-11**: 넘겨받은 값은 **경로 세그먼트 1개**로만 치환된다. `/`·`.`·`%`·`:`·`?`·`#`
  가 들어 있으면 거부한다(`value_pattern`이 이미 막더라도 이중으로 검사한다).
- **AC-B-010-12**: **스킴·호스트는 응답에서 오지 않는다.** 인덱스 템플릿에 적힌 값으로
  고정이다. 응답이 우리를 어디로도 보낼 수 없다.
- **AC-B-010-13**: 조립된 URL도 `policy.check_url`(SSRF 가드)과 **robots 검사**를 새로
  통과해야 한다. 첫 요청이 통과했다는 사실은 두 번째 요청의 근거가 아니다.
- **AC-B-010-14**: 항목당 총 요청 예산은 **3회**(엔드포인트 + 체인 포함).

예시 (`engine/api_index.yaml`):

```yaml
- host: crates.io
  url_pattern: "^/crates/(?P<crate>[A-Za-z0-9_-]+)/?$"
  source: "https://crates.io/data-access"
  verified_at: "2026-08-29"
  chain:
    - request: "https://crates.io/api/v1/crates/{crate}"
      response_kind: json
      select: "crate.max_stable_version"
      value_pattern: '^[0-9]+\.[0-9]+\.[0-9]+$'
      bind: version
    - request: "https://crates.io/api/v1/crates/{crate}/{version}/readme"
      response_kind: html      # 기존 추출기를 그대로 태운다
```

### 4-3. 인덱스 스키마와 나머지 계약

| 필드 | 필수 | 의미 |
|---|---|---|
| `host` | ✔ | 원문 URL의 호스트 (정확 일치) |
| `url_pattern` | ✔ | 적용 경로 정규식 — 템플릿에 치환할 캡처 그룹 포함 |
| `endpoints[]` 또는 `chain[]` | ✔ | 전자는 **순차 시도(첫 성공에서 멈춤)**, 후자는 §4-2의 2단 체인 |
| `response_kind` | ✔ | `json` \| `html` — `html`이면 기존 추출기 재사용 |
| `content_pointer` | `json`일 때 ✔ | 본문 경로 (예: `items[].body`) |
| `source` | ✔ | 해당 API의 **공식 문서 URL** — 출처 없는 항목 금지 |
| `verified_at` | ✔ | 마지막 실측 날짜 |

- **AC-B-010-1**: API 경로는 **HTTP 경로가 본문 획득에 실패한 뒤에만** 시도한다. 원문이
  정상인 사이트에 API 부하를 주지 않고, X의 비교 가능성도 지킨다.
- **AC-B-010-2**: 인덱스에 항목이 없으면 API를 **시도하지 않는다.** URL 조립·추측 금지.
- **AC-B-010-4**: API 경로에서는 **임퍼소네이션을 사용하지 않는다.** 정직한 UA
  (`open-reach/<version> (+<repo-url>)`)를 보낸다. 기계용으로 열어 둔 문을 브라우저인
  척하며 두드리지 않는다 — WAF 경로와 방향이 반대인 것이 맞다.
- **AC-B-010-5**: API가 인증·키를 요구하면(401, 또는 키 안내와 함께 오는 403) 즉시
  중단하고 `auth_wall`로 분류한다. 키를 발급받거나 저장하지 않는다(NG-1).
- **AC-B-010-6**: 쿼터 소진(StackExchange 익명 300/일 — 실측 `quota_remaining=294`)은
  `rate_limited`로 정직하게 실패한다. 쿼터를 늘리려 키를 만들거나 IP를 바꾸지 않는다(NG-7).
- **AC-B-010-7**: 성공 시 `attempts[]`에 `route="phase0"`인 시도가 남고, 결과에 사용한
  엔드포인트가 표기된다. 소비자가 HTML 본문과 구분할 수 있어야 한다.
- **`endpoints[]` 의 실제 동작(문서 정정, 2026-09-01)**: 위 표는 R2 리뷰 시점까지
  "병렬 요청(응답을 이어 붙임)"이라고 적혀 있었으나 `_run_endpoints` 는 **순차로 시도해
  첫 유효 본문에서 멈춘다.** 이어 붙이지 않는다. 병렬로 읽으면 AC-B-010-14 의 3회 예산이
  한 항목에서 한꺼번에 소모되는 것으로 오해되고, 실제로는 성공하면 1회로 끝난다.
  코드가 계약이고 문서가 틀렸던 자리다(NG-10).
- **`attempts[].endpoint` 는 착지 URL이다**: 리디렉션이 있으면 요청한 URL이 아니라
  **실제로 닿은 URL**을 남기고, 다르면 `notes` 에 `redirect: <from> -> <to>` 를 적는다.
  SC-9 의 "인덱스 외 요청 0건" 감사가 우리의 의도가 아니라 실제 요청을 보게 하기 위해서다.
- **AC-B-010-15**: 인덱스는 **최대 20 항목**. 초과·`source` 누락·`verified_at` 누락은
  로드 실패(exit 3). NG-9가 지문표에서 막은 "사이트 목록의 무한 증식"을, 인덱스에서는
  상한과 출처 의무로 막는다.
- **AC-B-010-18**: 응답에 라이선스 정보가 있으면(실측: `content_license: CC BY-SA 4.0`)
  결과에 함께 싣는다. 본문은 여전히 보관하지 않는다.

### 4-4. 측정 무결성 — R11의 교훈이 걸리는 자리

R11이 남긴 문장은 "측정 대상을 넓히는 변경은 측정 기준을 같이 조여야 한다"였다.
API 라우팅은 정확히 측정 대상을 넓히는 변경이다.

- **AC-B-010-16**: `bench` 출력은 `rate`와 함께 **`rate_http_only`**를 낸다. API 라우팅을
  켠 뒤에도 R1의 X(85.7%)와 **같은 정의의 값**이 사라지지 않는다.
- **AC-B-010-17**: `bench` 분해에 `rescued_by_phase0` 건수를 낸다. 돌파율이 올랐을 때 그것이
  전송 개선인지 API 구제인지 출력만 보고 갈릴 수 있어야 한다.

**예상 효과**: 60/70 → **63/70 (90.0%)**. 세 건 모두 구제 경로가 실측된 것이다.

### 4-5. 새 SC — R2에는 지금 게이트가 하나도 없다

SC-1~SC-7은 R1(1·3·4)과 R3(2·5·6·7)에만 걸려 있고 **R2에는 없다.** 라운드에 게이트가
없으면 "했다"의 판정이 서술로 남는다.

| ID | 이름 | 측정 | 임계 | Round |
|----|------|------|------|-------|
| **SC-8** | 벤더 감지 정확도 | 배터리 `expected.waf_vendor` vs 실행 시 감지값 | 오탐 **0건**(hard fail) AND 미탐 ≤10% | R2 |
| **SC-9** | API 라우팅 무결성 | API 구제 건 전수 감사 | robots 미검사 **0건**, 임퍼소네이션 사용 **0건**, 인덱스 외 요청 **0건**, `value_pattern` 미검증 치환 **0건** — 전부 hard fail | R2 |

SC-8의 오탐 0건이 hard fail인 이유는 R1에서 실제로 겪었기 때문이다 — Imperva 차단
페이지를 본문으로 오인해 "성공 2건"이 잡혀 있었다. 감지가 틀리면 그 위에 세운 모든
분해가 틀린다.

---

## 5. 측정 결과 — 근거가 없는 두 항목

사용자 결정 ②에 따라 처분 전에 실측했다. **둘 다 근거가 만들어지지 않았다.**

### 5-1. URL 변형 (`r2-variant-probe.json`)

두 축으로 쟀다. 변형은 우리가 지어내는 것이 아니라 문서가 가리켜 주거나, 최소한 효과가
있어야 정당하다.

**(가) 선언 빈도 — 0/8.** 성공 표본 8곳(`blog.rust-lang.org`·`theverge.com`·
`arstechnica.com`·`bbc.com`·`techcrunch.com`·`developer.mozilla.org`·`wikipedia.org`·
`nytimes.com`) 중 `<link rel="amphtml">`를 선언한 곳은 **한 곳도 없다.** AMP는 실무에서
사라졌다.

**(나) 차단 회피 — 0/12.** 403을 받는 4곳에 변형 3종을 걸었다.

| 변형 | g2 | crunchbase | netflixtechblog | stackoverflow |
|---|---|---|---|---|
| `/amp` 경로 | 403 (1,707B) | 403 (5,486B) | 403 (5,739B) | 403 (5,451B) |
| `?amp=1` | 403 (1,707B) | 403 (5,486B) | 403 (5,741B) | 403 (5,472B) |
| `m.` 호스트 | DNS 없음 | DNS 없음 | DNS 없음 | DNS 없음 |

바이트 수까지 원본 403과 사실상 동일하다 — WAF는 경로를 보고 있지 않다. **`m.` 호스트는
네 곳 전부 DNS에 존재하지 않는다.** 지문표가 akamai·unknown_challenge에 선언해 둔
`mobile`은 가리키는 대상이 없는 선언이다.

→ **처분: R2에서 제외.** 더불어 지문표의 `mobile` 선언을 제거한다. `SUPPORTED_VARIANTS`가
걸러 내므로 현재 동작에는 영향이 없지만, 실행되지 않는 계획을 데이터에 남겨 두는 것은
NG-10("계획에 없는 것을 계획에 있는 척하지 않는다")이 막으려는 상태 그 자체다.

### 5-2. yt-dlp 라우팅 (`r2-media-probe.json`, `r2-media-extract.json`)

셋을 쟀다. ① 리서치 대상에 미디어가 섞이나 ② HTTP 경로로는 정말 못 얻나 ③ robots가
허용하나.

| 대상 | robots | HTTP 경로 결과 | 판정 |
|---|---|---|---|
| `youtube.com/watch` | 허용 | HTML 1.39MB → 추출 **173자**(푸터·제목뿐) | **대상 실재** |
| `vimeo.com/76979871` | 허용 | 12.7KB → 271자, 내용은 *"Verify to continue… confirm that you're a human"* | **경계 밖** — CAPTCHA는 풀지 않는다 |
| `podcasts.apple.com/…` | 허용 | 579KB → **22,689자 정상 추출** | **불필요** — 이미 성공한다 |
| A1 표본 70건 | — | 미디어 URL **0건** | 수요 미확인 |

robots는 세 곳 다 허용이므로 ③은 장애물이 아니다. 그러나 남는 그림은 이렇다:
**yt-dlp 라우팅은 사실상 YouTube 한 곳을 위한 기능**이고, 표본에는 수요가 없으며,
가져오는 것은 기사 본문이 아니라 자막·설명이라 성공 정의가 또 하나 늘어난다. 게다가
외부 바이너리 의존이 추가되어 **SC-7("깨끗한 환경 설치 → 첫 `fetch`까지 사람 개입 0회")**
와 정면으로 부딪친다.

→ **처분: R2에서 제외, R4 이후 재검토.** 미디어 수요가 실제 사용에서 나타나면 그때
라운드를 잡는다.

(용어 정리: 코드에 이미 있는 `extract_media`/`intent=media`는 **문서 안의 미디어 링크
목록**을 뽑는 R1 기능이고, 여기서 말하는 yt-dlp 라우팅과 무관하다. SPEC에 둘이 함께
들어가면 같은 낱말이 두 뜻이 되므로, 개정 시 후자를 "미디어 텍스트 라우팅"으로 적는다.)

### 5-3. 부수 확인 — 남은 403 3건

`netflixtechblog`·`g2`·`crunchbase`는 §5-1의 변형 12회로도 뚫리지 않았고, 공개 API도
없다. R2 계약에는 넣지 않는다. `netflixtechblog`는 애초에 우리가 **200을 받는** 곳이며
(본문 268자 껍데기 → 티어 격상 후 403), 격차 분해에서 "성공 정의의 차이"로 분류된 건이다.

---

## 6. SPEC 반영 (사용자 승인 2026-08-29, 완료)

**이 문서가 아니라 `docs/SPEC.md`가 계약이다.** 아래는 승인받아 반영한 내역이며,
AC 번호는 SPEC의 최종 번호로 맞춰 두었다.

| # | SPEC 변경 | 성격 | 결과 |
|---|-----------|------|------|
| 1 | 「Round 경계」 R2 행 교체 + "R2에서 하지 않기로 확정한 것" 표(URL 변형·yt-dlp·격자 플래너와 각 제외 근거) + R2 종료 조건 | 범위 **축소** | 반영 |
| 2 | US-B-009(벤더 표본 확보와 감지 정확도) 신설 + AC 4종 | 범위 확정 | 반영 |
| 3 | US-B-010(Phase 0 공개 API 라우팅) 신설 + AC **18종** | 범위 확정 | 반영 |
| 4 | Success Criteria에 SC-8·SC-9 추가 | 게이트 **추가** | 반영 |
| 5 | Data Model에 `ApiIndexEntry`·`ChainStep` 추가 | 스키마 | 반영 |
| 6 | NG-9의 적용 범위를 지문표로 명시하고, API 인덱스는 상한 20 + 출처·검증일 의무 + 조립 규칙으로 대신 강제 | 경계 재확인 | 반영 |

**승인 시점의 5번 항목에서 하나가 빠졌다.** `Attempt.route`에 `api`를 추가하려 했으나,
SPEC이 R1부터 같은 자리를 **`phase0`** 으로 이미 예약해 두고 있었다. 한 가지 것에 이름을
둘 만들지 않기 위해 기존 값을 쓰고 스키마는 손대지 않았다 — 승인받은 것보다 **좁은**
변경이다. 이 문서의 `route` 표기도 `phase0`으로 통일했다.

**변경 1은 범위를 줄이는 개정이다.** auto-complete-loop의 `review-escalation-check`는
범위 축소를 승격 리뷰 트리거로 잡으므로, 구현 전 리뷰를 **dual 이상**으로 올린다.

**변경 3·6이 이번 계약의 위험 지점이다.** 2-hop은 상대 응답이 우리 요청 URL에 영향을
주는 첫 경로이고, 그 위험은 AC-B-010-8~14(체인 길이 2 · 스칼라 1개 · 앵커된
`value_pattern` 필수 · 세그먼트 1개 치환 · 호스트 고정 · SSRF·robots 재검사 · 요청 예산 3)
으로 가둔다. 이 중 하나라도 구현에서 빠지면 SC-9가 hard fail로 잡는다.

---

## 7. R2 게이트 실측 (2026-09-01)

### 7-1. SC-8 — 벤더 감지 정확도

출하 배터리(`bench --tier 1 --runs 1`, 양성 12 · 음성 7):

```
vendor_scope: ["cloudflare", "akamai", "fastly", "imperva", "datadome"]
              out_of_scope: ["aws_waf", "f5", "kasada", "perimeterx"]
by_vendor: {"akamai": 4, "cloudflare": 4, "datadome": 2, "fastly": 2}
vendor_accuracy: {"correct": 16, "false_negative": 0, "false_positive": 0,
                  "unmeasured": 0, "unresolved": 3}
vendor_sc8: {"false_negative": 0, "false_positive": 0, "measurable": 19,
             "miss_rate": 0.0, "unmeasured": 0}
vendor_misses: []
vendor_unresolved: ["dd-neg-002: 기대 datadome · 감지 datadome (귀속 실패,
                     출처 https://www.saksfifthavenue.com/)",
                    "cf-003: 기대 cloudflare · 감지 cloudflare (귀속 실패,
                     출처 https://fr.shopping.rakuten.com/)",
                    "fa-002: 기대 fastly · 감지 fastly (귀속 실패,
                     출처 https://rust-lang.org/)"]
BENCH_RESULT: rate=1.000 total=12 passed=12 failed=0
```

**SC-8 통과** — 오탐 0건(hard fail 축) AND 미탐 0% ≤ 10%(잴 수 있었던 19건 기준).
음성 7건도 전부 차단으로 분류됐다(G-3).

`unresolved` 3건은 코드 리뷰 H4 수정(§8)과 그 규칙을 좁힌 라운드 2 지적 6(§9)이 걸러 낸
것이다. 세 항목 모두 **다른 호스트로 리디렉션**되므로, 거기서 만난 WAF 판정을 배터리
URL 의 실력으로 계상할 수 없다. 판정 자체는 라벨과 일치했지만 귀속이 안 되므로
`correct` 가 아니라 `unresolved` 로 뺐다. `fa-002` 는 `www` 교차 한 건인데, `www` 를
같은 사이트로 쳐 주던 동안에는 `correct` 로 세어졌다 — WAF 는 호스트 단위로 붙으므로
그 계상은 근거가 없었다.
분모(`measurable`)에는 그대로 남긴다 — 빼 주면 "맞히기 어려운 항목을 리디렉션으로
치우면 정확도가 올라가는" 구멍이 생긴다.

측정 범위를 정직하게 적어 둔다. 정확도 19건은 **배터리 안**에서만 잰 값이다. 배터리
라벨 자체가 감지기 출력으로 만들어졌으므로 이 수치는 "감지기가 자기 자신과 일치한다"는
**회귀 고정**이지, 감지기가 세상의 WAF 를 맞힌다는 증거가 아니다. 후자는 라벨을 외부에서
얻어야 잴 수 있고, R2 범위 밖이다.

### 7-2. SC-9 — API 라우팅 무결성

출하 배터리에는 Phase 0 구제 대상이 없어(`rescued_by_phase0=0`) 프로덕션 실행으로는
전수 감사의 표본이 생기지 않는다. SC-9 는 인수 테스트
`tests/acceptance/us-b-010-api-routing-negative.sh` 에서 픽스처 오리진으로 잰다.

- **막힌 쪽** — chain 3단 / `value_pattern` 누락 / 호스트 바인딩 / 인덱스 21항목 /
  `verified_at` 누락은 전부 **로드 실패(exit 3) + 네트워크 요청 0건**. select 배열 ·
  패턴 불일치 · 경로 구분자 값 · robots Disallow · 요청 예산 초과는 2단 요청 0건.
  응답이 심어 둔 유혹(`next_url: /api/evil`)은 끝까지 **0회** 요청됐다.
- **통과한 쪽** — 2-hop 구제 성공 1건을 만들어 그 성공을 뜯어본다. 막힌 경로만 검사하면
  아무것도 성공하지 않아도 전부 통과하기 때문이다. 감사 결과: 임퍼소네이션 사용 0건 ·
  인덱스 밖 엔드포인트 0건 · phase0 요청 2건(=2-hop) · robots 조회 있음.
  `ACCEPTANCE_RESULT: total=10 passed=10 failed=0`.

> **AC-B-010-11 과 실물 API 의 충돌 (사용자 판단 필요).** AC-B-010-11 은 넘겨받은 값에
> `.` 이 있으면 거부한다. 그런데 실측으로 확인한 유일한 2-hop 후보인 crates.io 는
> `max_stable_version` 이 `1.0.219` 라 **정의상 완주할 수 없다**. 그래서 출하 인덱스
> (`skills/open-reach/engine/api_index.yaml`)에는 1-hop 한 항목만 있고, 사용자가 고른
> "2-hop 까지 허용"은 코드·테스트에만 있고 **출하 항목이 없다.**
>
> 계약을 우회하지 않았다. 인수 테스트의 2-hop 성공 케이스도 점이 없는 값(`doc`)으로
> 만들었다. 푸는 방법은 SPEC 개정 하나뿐이고, 제안은 아래와 같다 —
> **금지 문자를 `/`·`\`·`%`·`:`·`?`·`#` 로 두고, 점은 문자 단위로 막는 대신 값이
> `.` 또는 `..` **와 같을 때** 거부한다.** 세그먼트 이탈은 `.`/`..` 두 값과 구분자
> (`/`·`\`)로만 일어나므로 방어력은 같고, `1.0.219` 같은 정상 값이 통과한다.
> (`\` 는 원 AC 문언에 없지만 IIS 계열이 이를 경로 구분자로 정규화하므로 구현이
> 이미 막고 있다 — §8 C2.) `value_pattern` 앵커
> 필수와 세그먼트 1개 치환은 그대로 둔다. **개정 여부는 사용자 몫이다 — 승인 없이는
> 이 항목이 출하 인덱스에 들어갈 수 없다.**

---

## 8. 코드 리뷰 라운드 1 (codex, 2026-09-01)

R2 구현에 대해 `--mode codex` 리뷰를 돌렸고 **반려** 판정과 함께 9건(C 3 · H 4 · M 2)을
받았다. 8건 수정, 1건 반박. 라운드 종료 시점 검증: `pytest tests/unit -q` **61 passed**,
`bash tests/acceptance/run.sh` **total=10 passed=10 failed=0**, 출하 배터리 **exit 0**.

### 8-1. 수정한 것

| # | 지적 | 조치 |
|---|------|------|
| C1 | hop 가드가 SSRF 만 보고 **robots 를 다시 안 봤다** — AC-B-010-13 위반. 조립된 URL 과 리디렉션 목적지가 robots 검사를 우회할 수 있었다 | `policy.hop_guard()` 를 SSRF → `robots_verdict(next_url)` 순으로 확장. robots.txt 자체를 받을 때는 재귀를 피하려 `ssrf_hop_guard()` 만 쓴다 |
| C1' | API 체인의 리디렉션이 **다른 오리진으로 나갈 수 있었다** — AC-B-010-12(NG-11) 위반 | `api_index._same_origin_hop(origin)` 을 요청 경로에 배선 |
| C2 | AC-B-010-11 금지 문자에 `\` 가 없다 | `SEGMENT_FORBIDDEN` 에 `\` 추가. 문언에는 없지만 IIS 계열·일부 프록시가 `\` 를 경로 구분자로 정규화하므로 `a\..\..\admin` 이 세그먼트를 벗어난다. **계약의 문언이 아니라 계약의 목적을 지킨다** |
| C3 | 문서는 `endpoints[]` 를 "병렬 시도"라 적었는데 코드는 **순차(첫 성공에서 멈춤)** — 문서가 사실과 다르다(NG-10) | §4 표와 설명을 코드 쪽으로 정정. 여기서는 코드가 계약이고 문서가 틀렸다 |
| H1 | `bench` 는 API 인덱스를 **선검증하지 않았다**. 인덱스가 깨져 있으면 배터리를 절반쯤 돈 뒤에 죽고, 이미 나간 요청은 되돌릴 수 없다 | `engine.bench` 가 `fetch` 와 같은 자리에서 `api_index.load_cached(None)` 로 Phase 0 선검증. 인수 테스트에 "깨진 인덱스 → exit 3 AND 배터리 요청 0건" 케이스 추가 |
| H3 | SC-8 을 **출력만 하고 게이트로 쓰지 않았다** — 오탐이 나도 종료 코드가 0 | `bench.sc8_summary()` / `sc8_violations()` 순수 함수 + `engine.bench` 에서 exit 3. 기록(`record_run`)은 막히더라도 남긴다 — 다음 실행이 회귀를 봐야 하므로 |
| H4 | 리디렉션 뒤 WAF 판정이 **원래 URL 의 실력으로 계상**됐다 — 사이트 A 의 감지 결과가 사이트 B 점수가 되는 자리 | 판정과 함께 출처 URL(`trace["waf_origin"]`)을 남기고, `same_site()` 로 귀속을 확인. 귀속 실패면 `unresolved` (§7-1) |
| M1 | SPEC 은 `expected.waf_vendor`, 배터리는 `waf_expected` — 표기 불일치 | 양쪽을 다 읽고, **둘 다 있는데 값이 다르면** G-4 거버넌스 위반. 한 항목에 정답이 두 개면 점수는 "어느 쪽을 읽었나"에 달린다 |
| M2 | `us-b-009` 가 `false_positive == 0` 만 봤다 — SC-8 게이트를 통째로 지워도 초록 | 5-튜플 정확 대조(`6 0 0 0 0`) + `vendor_sc8` 출력 검사 + **의도적 오라벨 픽스처**(`tests/fixtures/battery-sc8-miss.yaml`, 미탐 1/6 = 16.7%)로 게이트가 실제로 닫히는지 검사 |

**H4 는 이론이 아니라 실제 결함이었다.** 수정 직후 출하 배터리에서 두 항목이 `correct`
에서 빠졌다 — `dd-neg-002`(→ `www.saksfifthavenue.com`)와 `cf-003`
(→ `fr.shopping.rakuten.com`). 둘 다 브랜드는 같지만 **호스트가 다르고**, 그 호스트의 WAF
판정이 원래 항목의 정답과 대조되고 있었다. 귀속 규칙은 호스트 일치(선행 `www.` 만 무시)로
고정했다 — 등록 도메인 단위로 느슨하게 하려면 공개 접미사 목록이 필요하고, 그 의존성을
지금 들이는 것보다 보수적으로 세는 편이 낫다.

`unresolved` 를 개수로만 내보내면 **어느 항목이 왜 빠졌는지 알 수 없어** 진단이 불가능하다
(`vendor_misses` 에 이미 적용한 논리). 그래서 `vendor_unresolved` 에 항목 id · 기대 · 감지 ·
사유 · 출처를 함께 싣는다.

### 8-2. 반박했다가 기각된 것 (H2)

**결론부터: 반박은 라운드 2에서 기각됐고, 고쳤다.** 아래에 원래 주장과 무엇이 틀렸는지를
지운 자국 없이 남긴다.

> **지적**: robots.txt 조회와 리디렉션이 AC-B-010-14 의 "한 항목 총 요청 예산 3회"에
> 계상되지 않는다.

수정하지 않았다. AC-B-010-14 의 괄호가 예산의 범위를 스스로 정의한다 —
**"3회(엔드포인트 + 체인 포함)"**. 즉 예산은 *우리가 인덱스를 근거로 고른 요청*을 세는
장치이고, robots 조회는 그 요청을 **허가받기 위한** 부수 요청, 리디렉션은 상대가 강제한
이동이다. 이것들을 예산에 넣으면 robots 를 성실히 조회할수록 예산이 줄어 **검사를 건너뛸
동기**가 생긴다 — 게이트가 게이트를 갉아먹는 배선이다.

넓히는 쪽이 옳다고 판단되면 그건 구현 수정이 아니라 **AC 문언 개정**이고, 개정은 사용자
승인 사항이다. 계약 문언을 조용히 넓히지 않는다.

**무엇이 틀렸나.** 위 주장은 "예산이 무엇을 세는가"만 따졌고, **회선에 실제로 몇 번
나가는가**는 세지 않았다. `budget[0]` 은 우리가 `_request()` 를 부른 횟수를 세는데, 요청
하나는 리디렉션을 따라가며 최대 `MAX_REDIRECTS`(5) 번 더 나간다. 엔드포인트 3개가 각각
5홉을 돌면 실제 요청은 `3 x 6 = 18` 회 + robots 다. 인덱스 20항목 상한은 항목 수 제한일
뿐이고, 체인 2단 상한은 `endpoints` 형식에 적용되지 않으며, same-origin 규칙은 같은
오리진 안의 5홉을 막지 않는다. **닫혀 있다고 주장한 증폭 경로가 열려 있었다.**

문언 해석은 그대로 두고 — AC-B-010-14 의 3회는 여전히 "인덱스를 근거로 고른 요청"을
센다 — **실제 요청 총량에 별도 상한**을 얹었다. `transport.dispatch_budget(n)` 은 홉
루프 안에서 dispatch 마다 차감하므로 리디렉션도 robots 도 전부 계상된다. 항목당 상한은
식으로 고정한다:

```
DISPATCH_BUDGET = REQUEST_BUDGET * 2 + 1 = 7
  인덱스 요청 3 + 요청당 리디렉션 1홉 + 오리진당 robots 1회
  (오리진은 AC-B-010-12 로 고정 → robots 는 항목당 최대 1회)
```

숫자를 주석으로만 정당화하면 다음 사람이 8로 바꾸고 주석을 고친다. 그래서 이 식 자체를
단위 테스트로 고정했다(`test_entry_dispatch_budget_is_derived_from_the_contract`).
초과 시 `PolicyBlocked("request_budget")` 이고, 이는 `run()` 이 이미 잡는 예외군이다.

---

## 9. 코드 리뷰 라운드 2 (codex, delta-only, 2026-09-01)

라운드 1의 수정에 대해 delta-only 리뷰를 돌렸다 — 각 수정이 **(a) 실제로 닫혔는지**
(막아야 할 코드 변형을 만들어 테스트가 정말 잡는지) **(b) 새 결함을 만들지 않았는지**만
보게 하고, 그 밖의 지적에는 "라운드 1이 왜 놓쳤는지"를 요구했다. 판정: **반려**,
6건(HIGH 4 · MEDIUM 2). CRITICAL·LOW 없음. 소스 지문 `08889483…-dca24828…`.

**라운드 1 판정: closed = H1 · H3 · M1 · M2 / not closed = C1 · C1' · C2 · C3 · H4.**
닫히지 않은 것 다섯 중 셋(C1·C2·H4)은 **구현은 있는데 그 구현을 지워도 테스트가 초록**인
경우였다. 이번 라운드의 절반이 그 지적이다.

| # | 심각도 | 지적 | 조치 |
|---|---|---|---|
| 1 | HIGH | C1' 의 same-origin 차단이 **robots 요청 뒤에** 실행된다. 인덱스 API 가 `tracker.example` 로 302 하면 본문 요청은 막지만 `tracker.example/robots.txt` 는 이미 두드린 뒤이고, 그 요청은 `attempts[]` 에도 안 남는다 | `_same_origin_hop._check` 에서 오리진 검사를 `hop_guard` **앞**으로 옮김 |
| 2 | MEDIUM | C1 을 죽이는 테스트가 없다 — `hop_guard` 에서 robots 검사를 빼도 초록 | 루프백 픽스처를 테스트 안에서 띄워 `302 → robots Disallow 경로` 를 만들고 차단 + 목적지 hit 0 단언 |
| 3 | MEDIUM | C2 를 죽이는 테스트가 없다 — `SEGMENT_FORBIDDEN` 에서 `\` 만 지워도 기존 픽스처 값은 `/` 를 포함해 계속 거부되므로 초록 | `substitute()` 파라미터화 테스트에 `a\b` 단독 케이스 추가 |
| 4 | HIGH | C3 는 R2 문서만 고쳤고 **동결된 SPEC 은 그대로** — `docs/SPEC.md:274` 가 `endpoints` 를 "병렬 요청 후 응답을 이어 붙이는" 형태라고 규정해 구현과 충돌한다 | **미해결 — 사용자 승인 대기.** §9-1 참조 |
| 5 | HIGH | H2 반박 기각. 예산이 실제 요청을 3회로 제한하지 않는다 (`3 x 6 = 18` + robots) | dispatch 미터 도입 (§8-2) |
| 6 | HIGH | H4 의 귀속 규칙이 `www.` 를 벗겨 교차 호스트 판정을 다시 `correct` 로 되돌린다. apex 는 WAF 없이 `www` 만 Cloudflare 뒤에 두는 배치가 실재하고, **WAF 설정 단위는 호스트다** | `same_site()` 를 소문자 정규화만 한 정확한 호스트 일치로 변경 |

지적 6의 판정에서 codex 는 "명백히 다른 호스트인 `dd-neg-002`·`cf-003` 를 `unresolved`
로 빼고 분모에는 남긴 판단 자체는 맞다"고 확인했다. 규칙만 좁혔다.

### 9-1. 미해결 — SPEC 개정 승인이 필요하다 (지적 4)

`docs/SPEC.md:274`:

> | `endpoints` | str 배열 또는 null | … | **병렬 요청 후 응답을 이어 붙이는** 단순 형태 |

구현(`_run_endpoints`)은 **순차로 시도하고 첫 유효 본문에서 멈춘다.** 라운드 1에서 이
불일치를 문서 쪽 오류로 보고 `docs/r2-contract.md` 만 고쳤는데, 그것으로는 부족하다 —
SPEC 은 해시 동결된 계약이고, "코드가 계약"이라는 선언이 동결된 문서를 대체할 수 없다.
지금 상태는 **구현이 계약을 위반하고 있는 것**이다.

두 가지 길이 있고, 어느 쪽이든 사용자 승인 사항이다.

- **(A) SPEC 을 구현에 맞춘다 (권장).** 274행을 "순차로 시도하고 **첫 유효 본문에서
  멈추는** 단순 형태"로 바꾼다. 근거: 출하 인덱스의 유일한 항목은 엔드포인트가 하나이고,
  여러 엔드포인트의 본문을 이어 붙여야 하는 실측 사례가 없다. 병렬·결합은 요청 수를
  늘리기만 하고 §8-2 의 요청 총량 상한과도 정면으로 부딪힌다.
- **(B) 구현을 SPEC 에 맞춘다.** 엔드포인트를 모두 요청해 본문을 이어 붙인다. 근거 없는
  요청이 늘고, 첫 응답으로 충분한 경우에도 나머지를 쏘게 된다.

승인 없이는 어느 쪽도 하지 않는다. 이 항목은 R2 완료 조건에 **미해결로 남아 있다.**

---

## 10. 코드 리뷰 라운드 3 (codex, delta-only, 2026-09-01)

판정 **반려**. CRITICAL 0 · HIGH 2 · MEDIUM 2 · LOW 0.
귀속 지문 `08889483169c0d48d0494b12ea89894d2f894fd4-498c69ab…`.
라운드 2 항목 판정: **closed = #1·#2·#3·#6**, **not closed = #4·#5**.

> **정정 (라운드 4)** — 아래 10-1 의 처방 중 `policy.ROBOTS_MAX_REDIRECTS` 와
> `DISPATCH_BUDGET = 12` 는 **철회됐다.** robots 조회에 홉 상한을 건 것이 조회의
> fail-open 과 결합해 실제 `Disallow` 를 우회시켰기 때문이다(§11-1). 지금 코드에
> `ROBOTS_MAX_REDIRECTS` 는 없고 상한은 27 이다. 이 절은 당시의 판단을 남겨 둔 기록이며
> 현재 동작이 아니다 — 현재 동작은 §11 을 본다.

| # | 지적 | 분류 | 처리 |
|---|------|------|------|
| 1 | `DISPATCH_BUDGET = 7` 의 전제("오리진 하나·요청당 홉 하나")를 코드가 강제하지 않는다 | HIGH (b, 신규 결함) | 상한을 늘리는 대신 **전제를 강제**로 바꿈 |
| 2 | `run()` 에서 `with transport.dispatch_budget(...)` 을 지워도 초록 | MEDIUM (b) | `run()` 만 부르는 미터 배선 테스트 추가 |
| 3 | `request_budget` 이 `POLICY_RULES` 밖 값이라 `attempts[].rule=None` — SPEC:229 위반 | MEDIUM (b) | 예산 초과를 `PolicyBlocked` 에서 **분리**(SPEC 개정 불필요) |
| 4 | SPEC:274 `endpoints` 병렬 vs 순차 | HIGH (a, 미해결) | 코드 변경 없음 — §9-1 그대로, 승인 대기 |

### 10-1. #1 — 상한을 올리지 않고 전제를 강제했다

라운드 2의 산식은 이랬다.

> 인덱스 요청 3 + 요청당 리디렉션 1홉 + 오리진당 robots 1회 = 7

두 항 모두 **가정**이었다. `endpoints` 는 서로 다른 오리진을 가리킬 수 있고(검증기가
막지 않는다), 전송 계층은 홉을 5회까지 따라간다. 오리진 3개짜리 정상 항목이라면
robots 3 + 본 요청 3 + 홉 3 = **9회**로 8번째에서 막힌다 — 가드가 조용히 **기능 회귀**가
된 것이다. 게다가 robots 조회 자체도 `transport.request` 라서 robots.txt 가 리디렉션
사슬이면 조회 하나가 회선에 6번까지 나간다.

상한을 24로 올리면 산식은 참이 되지만 라운드 2가 막으려던 증폭(18회)을 다시 허용한다.
그래서 **가정을 강제된 값으로 바꿨다**.

- `api_index.PHASE0_MAX_REDIRECTS = 1` — `_same_origin_hop` 이 홉을 세고 네트워크에
  나가기 전에 끊는다.
- `policy.ROBOTS_MAX_REDIRECTS = 1` — robots 조회 전용 홉 가드(`_robots_hop_guard`)가
  같은 일을 한다. 조회 실패는 SPEC대로 fail-open 이지만 홉은 상한에서 끊긴다.
- 두 상한이 실재하므로 산식의 각 항이 이제 **코드가 허용하는 최대치**다.

```python
DISPATCH_BUDGET = (
    REQUEST_BUDGET * (1 + PHASE0_MAX_REDIRECTS)            # 본 요청 + 홉
    + REQUEST_BUDGET * (1 + policy.ROBOTS_MAX_REDIRECTS)   # 오리진당 robots + 홉
)   # = 12
```

오리진 3개·각 1홉의 최악 정상 항목(9회)이 통과하고, 라운드 2가 지적한 18회는 여전히
막힌다. 단위 테스트가 식과 그 최악 시나리오를 함께 고정한다.

### 10-2. #3 — 예산 초과는 정책 차단이 아니다

`_count_dispatch` 가 `PolicyBlocked("request_budget", …)` 을 던졌는데, 이 값은
`PolicyVerdict.rule` 도메인(SPEC.md:344) 밖이다. `fetcher` 는 도메인 밖 값을 `None` 으로
떨어뜨리므로 `route="policy"` 인데 `rule` 이 비는 상태가 되고, 이는 SPEC.md:229 위반이다.

codex 의 최소 수정안은 "사용자 승인 후 `request_budget` 을 SPEC 과 `POLICY_RULES` 에
추가"였다. 그러나 동결 SPEC 을 여는 것보다 **분류가 애초에 틀렸다**고 보는 쪽이 맞다.
정책 차단은 상대가 내린 판정이고(robots·SSRF), 요청 예산은 우리가 우리에게 건 상한이다.
그래서 `transport.BudgetExceeded` 를 별도 예외로 두고 `run()` 이 `_BudgetExhausted` 와
같은 자리에서 받는다 — `reason` 은 `None`(구제 실패), `policy_rule` 도 `None` 이다.

부수 효과가 하나 더 닫혔다. `policy.robots_verdict` 는 robots 조회 실패를
`(NetworkError, PolicyBlocked)` 로 삼켜 **fail-open** 시킨다. 예산 초과가 `PolicyBlocked`
였다면 "robots.txt 조회 실패 — 기본 허용"으로 세탁되어, 상한을 넘긴 사실이 로그에서
사라지고 robots 판정까지 느슨해졌다. 별도 타입이라 이제 그대로 위로 올라간다.

### 10-3. 남은 것

#4(SPEC:274) 하나다. §9-1 의 (A)/(B) 그대로이며 승인 없이는 어느 쪽도 하지 않는다.
(10-1 의 처방은 라운드 4 에서 철회됐다 — §11-1.)

## 11. 코드 리뷰 라운드 4 (codex, delta-only, 2026-09-01)

판정 **반려**. CRITICAL 0 · HIGH 3 · MEDIUM 1 · LOW 0.
귀속 지문 `08889483169c0d48d0494b12ea89894d2f894fd4-38e420e5a…`.
라운드 3 항목 판정: **closed = #2·#3**, **not closed = #1·#4**.

세 지적 중 **둘이 내가 라운드 3 에서 만든 결함**이다. 하나는 윤리 경계를 뚫었다.

| # | 지적 | 분류 | 처리 |
|---|------|------|------|
| 1 | robots 홉 상한 초과를 "조회 실패"로 삼켜 실제 `Disallow` 를 우회 | HIGH (b, 라운드 3 이 만듦) | 상한 **전면 철회** |
| 2 | `PHASE0_MAX_REDIRECTS = 1` 이 정상 2홉 정규화 API 를 막는다 | HIGH (b) | 2 로 상향 + docstring 정정 |
| 3 | SPEC:274 `endpoints` 병렬 vs 순차 | HIGH (a, 미해결) | 승인 대기 — §9-1 |
| 4 | 예산 소진 뒤 `_guard` 가 먼저 돌아 "오리진 수 ≤ 요청 수" 가 거짓 | MEDIUM (b) | `_reserve` 를 `_guard` **앞**으로 |

### 11-1. #1 — 상한을 지키려다 경계를 뚫었다

라운드 3 에서 `DISPATCH_BUDGET` 산식을 참으로 만들려고 robots.txt 조회의 리디렉션에
1홉 상한(`policy.ROBOTS_MAX_REDIRECTS`)을 걸었다. 그런데 robots **조회 실패는 SPEC 상
fail-open** 이다(`robots_verdict` 의 `except (NetworkError, PolicyBlocked)`). 두 개가
만나면 이렇게 된다.

```
https://site.example/robots.txt -> /r1 -> /r2      (/r2 에 Disallow: /private)
  2번째 홉에서 PolicyBlocked("redirect_hop")
  -> robots_verdict 가 삼킨다 -> "조회 실패 — 기본 허용"
  -> 빈 규칙 집합을 오리진 캐시에 저장
  -> 이후 /private 본문을 그대로 요청한다
```

`Disallow` 를 존중한다는 것은 이 프로젝트의 금지선(NG)이지 최적화 항목이 아니다.
성능 상한을 위해 그 선을 넘은 것이고, 더 나쁜 것은 **내가 쓴 테스트가 그 동작을
"허용"으로 고정**했다는 점이다. 상한을 철회하고, 요청 총량은 `transport.MAX_REDIRECTS`
(이미 강제되고 있는 값)에서 유도하도록 바꿨다.

```python
DISPATCH_BUDGET = (
    REQUEST_BUDGET * (1 + PHASE0_MAX_REDIRECTS)          # 본 요청 + 홉
    + REQUEST_BUDGET * (1 + transport.MAX_REDIRECTS)     # 오리진당 robots + 홉
)   # = 3*3 + 3*6 = 27
```

교훈은 코드 주석에 그대로 남겼다 — **상한은 이미 강제되고 있는 것에서만 유도한다.**
두 번 틀렸는데, 라운드 2 는 강제되지 않는 전제 위에 세웠고, 라운드 3 은 그 전제를
참으로 만들려다 경계를 건드렸다.

회귀 잠금은 `test_redirecting_robots_still_yields_its_disallow` 다. 상한을 되살리는
변이를 실제로 넣어 확인했고, 실패 메시지가 우회 경로 그 자체였다 —
`PolicyVerdict(allowed=True, detail='robots.txt 조회 실패 (robots 홉 상한) — 기본 허용')`.

### 11-2. #2 — 1홉은 너무 조였다

끝 슬래시 정규화 뒤 버전 경로 정규화(`/v1/x` → `/v1/x/` → `/api/v1/x/`)처럼
같은 오리진 안에서 두 번 리디렉션하는 API 가 실재한다.
1홉이면 정상 항목이 `redirect_hop` 정책 위반처럼 보고된다. 2 로 올렸다.
(오리진을 넘는 홉은 여전히 0홉에서 차단이다 — `origin_of` 가 스킴을 포함하므로
`http→https` 도 오리진 변경으로 막힌다. 라운드 3 docstring 이 이를 반대로 적어 놓았기에
함께 정정했다 — NG-10.)

### 11-3. #4 — 쏘지 않기로 한 엔드포인트의 판정을 결과로 쓰지 않는다

`_run_endpoints`·`_run_chain` 은 `_guard(url)` → `_request(url)` 순서였고 예산 검사는
`_request` 안에 있었다. 앞 3개가 404 로 예산을 다 쓴 뒤 4번째가 robots Disallow 경로면,
가드가 먼저 돌아 항목 결과가 `policy_blocked` 로 보고되고 그 판정을 받으려고 robots.txt 를
한 번 더 두드린다. "오리진 수 ≤ 요청 수" 라는 산식 전제가 거짓이 되고, 감사 관점에서는
**우리가 쏘지 않기로 한 대상의 정책 판정**을 결과로 쓴 것이다.

`_reserve(budget)` 를 `_guard` 앞으로 뺐다. 이제 예산이 0 이면 네트워크에 나가기 전에
`_BudgetExhausted` 로 끊기고 `reason` 은 `None`(구제 실패)이다.
`test_exhausted_budget_is_not_reported_as_a_policy_block` 이 루프백 서버로 이를 고정하며,
순서를 되돌리는 변이에서 실제로 빨개지는 것을 확인했다.

### 11-4. 검증

- `pytest tests/unit -q` → **83 passed** (신규 2종, 변이 사멸 2건 실증)
- `bash tests/acceptance/run.sh` → total=10 passed=10 failed=0
- 동결 인수 테스트 12종 무변경 — 이번 라운드는 프로덕션 코드와 단위 테스트만 건드렸다

### 11-5. 남은 것

#3(SPEC:274) 하나다. 사용자는 **순차 첫 성공**(§9-1 의 (A))이 적합하다는 판단을 밝혔고,
그것이 현재 구현과 일치한다. 다만 SPEC 은 해시 동결이므로 개정은
`acceptance-freeze --approved-by-user` 재동결로만 가능하다 — 승인 대기 중이다.

## 12. 코드 리뷰 라운드 5 (codex, delta-only, 2026-09-01)

판정 **반려**. CRITICAL 0 · HIGH 3 · MEDIUM 1 · LOW 0.
귀속 지문 `08889483169c0d48d0494b12ea89894d2f894fd4-05bebc167…`.
라운드 4 항목 판정: **closed = #3**, **not closed = #1·#2·#4**.

이번 라운드는 **프로덕션 결함이 0건**이다. 산식·SSRF 커버리지·예산 차감을 항별로
검증받았다(아래 12-0). 남은 세 지적은 전부 **회귀 테스트가 변이를 못 잡는다**는 것이고,
전부 맞는 말이다.

| # | 지적 | 분류 | 처리 |
|---|------|------|------|
| 1 | robots 사슬 회귀 테스트가 2홉뿐 — 상한 2 재도입을 놓친다 | HIGH (a) | 사슬 깊이를 `transport.MAX_REDIRECTS` 에서 유도 |
| 2 | 홉 테스트가 상수를 반복 횟수로 써서 상수 회귀를 못 잡는다 | HIGH (a) | 값 고정 + `run()` 2홉 통과 통합 테스트 |
| 3 | §11-2 의 `http→https` 예시가 바로 아래 서술과 모순 | MEDIUM (c) | 같은 스킴 경로 정규화 예시로 교체 |
| 4 | SPEC:274 `endpoints` 병렬 vs 순차 | HIGH (a) | 승인 대기 — §9-1 |

### 12-0. 프로덕션 코드에 대해 받은 판정

- 요청 총량: `endpoints` 최대 `3 × (robots 6 + 본 요청 3) = 27`, `chain` 은 길이 2 제한으로
  최대 `2 × (6 + 3) = 18`. **산식의 각 항이 코드가 실제로 허용하는 최대치**임을 확인받았다.
- `_reserve` 가 `_guard` 보다 앞이라 오리진 수가 요청 예산을 넘지 않고, 오리진별 robots
  캐시는 횟수를 **줄일 뿐 늘리지 않는다**. 이중/누락 차감 없음 — `_reserve` 는 검사만,
  `_request` 만 1회 차감.
- robots 리디렉션의 최초 URL 은 사전 검사되고 각 목적지는 다음 dispatch **전에**
  `ssrf_hop_guard` 를 거친다. 상한을 없앤 뒤에도 private-range SSRF probe 는 되지 않고,
  공개 리디렉션 증폭은 항목당 27 로 묶인다. `BudgetExceeded` 는 fail-open 대상이 아니다.

라운드 2·3·4 를 관통한 "상한을 강제되지 않는 전제 위에 세운다" 계열은 여기서 닫혔다.

### 12-1. #1·#2 — 상수에 맞춘 테스트는 그 상수를 지키지 않는다

두 지적은 같은 실수의 두 얼굴이다. 라운드 4 에서 나는 회귀 테스트를
`range(api_index.PHASE0_MAX_REDIRECTS)` 로, robots 사슬을 2홉으로 썼다. 상수를 읽어
쓰면 상수가 바뀌어도 테스트는 초록이고, 사슬이 2홉이면 "상한 2 로 재도입"이 통과한다.
**회귀 테스트가 검증 대상을 자기 기준으로 삼으면 아무것도 검증하지 않는다.**

- 사슬 깊이를 `ROBOTS_CHAIN_END = transport.MAX_REDIRECTS + 1` 로 유도했다. 픽스처가
  `/robots-N.txt` 를 동적으로 이어 붙이므로 전송 계층 상한이 바뀌면 따라간다.
- `test_phase0_hop_cap_value_is_pinned` 이 값 자체(2)를 못 박고, 그 이유를 적었다.
- `test_run_follows_a_legitimate_two_hop_normalisation` 이 `run()` 으로
  `/hop1 → /hop2 → /hop3` 을 실제 통과시킨다 — 값 고정만으로는 "상수는 2인데 코드가
  1홉에서 끊는" 상태를 못 잡기 때문이다.

codex 가 지목한 두 변이를 그대로 넣어 확인했다. 상한 2 재도입 → robots 테스트 red,
`PHASE0_MAX_REDIRECTS = 1` → 값 테스트와 `run()` 통합 테스트 **둘 다** red.

### 12-2. 검증

- `pytest tests/unit -q` → **85 passed** (신규 2종, 변이 사멸 3건 실증)
- `bash tests/acceptance/run.sh` → total=10 passed=10 failed=0
- 동결 인수 테스트 12종 무변경 — 이번 라운드는 단위 테스트와 문서만 건드렸다

### 12-3. 남은 것

#4(SPEC:274) 하나다. 라운드 3 부터 세 라운드 연속 같은 자리에 있고, 성격상 코드로는
닫을 수 없다 — 동결 SPEC 재동결 승인이 유일한 경로다.

## 13. 코드 리뷰 라운드 6 + SPEC 개정 (codex, delta-only, 2026-09-01)

### 13-0. 라운드 5 항목의 종결 판정

codex 가 직접 변이를 주입해 확인했다 — 내 주장을 받아 적은 것이 아니다.

| 라운드 5 항목 | 판정 | 근거 |
|---|---|---|
| 1 robots 사슬 깊이가 상수에 묶여 있었다 | **closed** | `ROBOTS_CHAIN_END = transport.MAX_REDIRECTS + 1` 로 유도되므로 상한 2 재도입이 red |
| 2 홉 테스트가 상수를 읽어 자기 자신을 지키지 못했다 | **closed** | 값 고정 테스트 + `run()` 통합 테스트 둘 다 `PHASE0_MAX_REDIRECTS = 1` 에서 red |
| 3 §11-2 문서 모순 | **closed** | 동일 스킴 경로 정규화 예시로 교체됨 |
| 4 SPEC:274 | 미종결 (재동결 전) | 이 라운드에서 승인·재동결로 닫힘 |

공유 상태로 인한 공허한 통과 가능성도 함께 기각됐다 — `HITS.clear()` 와 robots 캐시
clear 가 매 테스트 전 실행되므로 모듈 범위 서버·랜덤 순서·호스트 rate limiter 가
`/hop3 == 1` 을 가짜로 만들 수 없다.

### 13-1. HIGH 2건 — 둘 다 편집 중 스냅샷

codex 가 리포지토리를 **내가 개정을 적용하는 중에** 읽었다. 그래서 두 HIGH 는
"SPEC 은 점을 허용하는데 코드와 테스트는 점을 거부한다" 는 한 쌍의 불일치로 보고됐고,
코드 절반(`api_index.py:75`)은 이미 반영돼 있었다. 남은 절반은 실제로 유효했다:

- `tests/unit/test_api_routing_guards.py:148` 의 parametrize 에 `"a.b"` 가 남아 있어
  **개정과 반대되는 것을 단언**하고 있었다. 제거하고, 완화가 열어 준 구멍을 막는
  테스트를 함께 넣었다: `.`/`..` 세그먼트 거부 2종, 점 버전 허용 1종,
  `SEGMENT_FORBIDDEN`/`SEGMENT_DOT_ONLY` 값 고정 1종.

라운드 5 의 교훈("상수를 읽어 오는 테스트는 그 상수를 지키지 못한다")을 그대로 적용해
값 고정 테스트를 같이 넣은 것이지, 개정 사실을 다시 적은 것이 아니다. 변이 2종으로 확인:
`SEGMENT_FORBIDDEN` 에 `.` 재삽입 → 2종 red, `SEGMENT_DOT_ONLY` 검사 무력화 → 2종 red.

### 13-2. SPEC 개정 2건 (사용자 승인)

성격이 다른 둘을 한 번에 재동결했다.

1. **SPEC:274** — `endpoints` 를 "병렬" 로 적어 둔 것이 구현(`_run_endpoints` 는 순차로
   시도하고 첫 유효 본문에서 멈춘다)·요청 예산(`REQUEST_BUDGET = 3`)과 모순이었다.
   **문서가 코드를 잘못 적은 것**이고, 라운드 2 부터 5라운드 동안 open 이었다.
   코드로 닫을 수 없었던 이유는 SPEC 이 해시 동결이라 승인 없이는 못 고치기 때문이다.
2. **SPEC:190 (AC-B-010-11)** — 점을 세그먼트 이탈 **문자**로 금지한 조항이
   `1.0.229` 같은 버전 세그먼트를 정의상 불가능하게 만들어, **R2 계약이 허용한 2-hop 을
   계약 자신이 막고 있었다.** 점은 문자로 허용하고, 값 자체가 `.` 또는 `..` 인 경우를
   거부하도록 바꿨다. 완화가 경로 탈출을 열어 주지 않게 하는 것이 핵심이라,
   동결 인수 테스트에 `step1-dotdot.yaml` 음성 케이스를 넣어 경계를 못 박고,
   `ok2hop` 체인을 점 포함 버전으로 교체해 **양성 경로도** 동결했다.

재동결: 13 files + `docs/SPEC.md`, specHash `6aed2d27…` → `d80666c5…`.

### 13-3. 개정의 원래 동기는 달성되지 않았다

:190 을 고친 이유는 crates.io 2-hop 항목을 출하하기 위해서였다. **그 항목은 여전히
출하되지 않는다.** 벽이 하나가 아니라 둘이었고, 하나만 풀렸다.

실측 (2026-09-01, `bench/evidence/r2-crates-2hop-live-2026-09-01.json`):

```
1단  /api/v1/crates/serde            -> 200, max_stable_version = "1.0.229"   (성공)
2단  /api/v1/crates/serde/1.0.229/readme
       -> https://static.crates.io/readmes/serde/serde-1.0.229.html          (오리진 이탈)
결과 policy_blocked / redirect_hop  (AC-B-010-12, NG-11)
```

즉 개정은 **1단을 통과시키는 데는 실제로 성공했다** — 점 규칙이 살아 있었다면 여기서
멈췄을 것이다. 막은 것은 두 번째 벽이다: 응답이 우리를 다른 호스트로 보내려 했고,
NG-11 이 그것을 거부했다.

`r2-payload-probe.json` 의 "200 / text/html / 3,511B" 가 이 벽을 보여 주지 못한 이유도
분명하다 — **그 프로브는 우리 오리진 가드 없이 리디렉션을 따라갔다.** 우리 계약을
적용하지 않은 측정은 우리 계약 아래의 실현 가능성을 증명하지 못한다. 이것이 이
라운드에서 얻은 일반 교훈이고, 앞으로의 구제 후보 측정은 엔진을 통해서 한다.

우회로는 두 개가 있었고 둘 다 택하지 않았다.

- **오리진 가드 완화** — 윤리 경계(NG-11)다. 선택지에 올리지 않는다.
- **`static.crates.io` URL 을 인덱스 리터럴로 조립** — 스킴·호스트가 템플릿 고정이므로
  AC-B-010-12 는 만족한다. 그러나 그 URL 형식(`/readmes/{name}/{name}-{version}.html`)은
  공식 문서에 없어 **AC-B-010-15 의 `source` 의무를 채울 수 없다.** 한 번 관찰한 패턴을
  문서화된 계약인 척 적는 것은 NG-10 이다.

따라서 항목을 `engine/api_index.yaml` 에서 제거하고, "여기에 없는 것과 그 이유" 주석에
두 벽을 분리해 기록했다 — ①점 규칙(해소됨) ②오리진 이탈(미해소, 증거 파일 명시).
출하 인덱스는 stackoverflow.com 1항목으로 돌아갔다.

**그럼에도 개정 자체는 되돌리지 않았다.** :190 은 crates.io 와 무관하게 옳다 —
버전 문자열은 정상 세그먼트이고, 실제 경로 탈출은 `.`·`..` 세그먼트와 `/`·`\`·`%` 로 막힌다.
개정 전 규칙은 공격을 막는 대신 정상 값을 막고 있었다. 그 사실은 동결된 `ok2hop` 체인이
픽스처에서 2-hop 을 실제로 완주하는 것으로 증명된다.

### 13-4. 검증

- `pytest tests/unit -q` → **88 passed** (신규 4종, 변이 사멸 2건 실증)
- `bash tests/acceptance/run.sh` → total=10 passed=10 failed=0
- `acceptance-freeze --approved-by-user` → PASS (13 files + SPEC)
- 출하 배터리 → `BENCH_RESULT: rate=1.000 total=36 passed=36 failed=0`,
  `vendor_sc8: false_negative=0 false_positive=0 miss_rate=0.0`, `regression=none`

### 13-5. 남은 것

라운드 2 부터 열려 있던 #4 가 닫히면서 **open CRITICAL/HIGH 는 0건**이다.
이번 라운드의 수정은 테스트·문서·출하 인덱스 1항목 제거이고 프로덕션 로직은 건드리지
않았다. 리뷰 예산(수정 발생 라운드 5회)은 라운드 1~5 로 소진됐으므로, 라운드 7 은
소스 지문 귀속을 위한 **재기록 라운드**로 돌린다 — 상한 비포함이다.

## 14. 코드 리뷰 라운드 7 (codex, delta-only, 2026-09-01)

### 14-0. 라운드 6 항목 종결

둘 다 **closed**. codex 가 변이를 직접 주입해 확인했다 — `SEGMENT_FORBIDDEN` 에 `.` 재삽입
시 dotted-version 테스트가 `Rejected`, constants-pinned 가 `AssertionError` 로 red;
`SEGMENT_DOT_ONLY` 를 비우면 `.`/`..` 거부 테스트가 red. 즉
`test_segment_rules_are_pinned` 는 상수를 되읊는 tautology 가 아니라 리터럴 기댓값을
고정한다는 것도 함께 확인됐다.

### 14-1. HIGH — 완화가 연 표면은 점이 아니라 **서버 정규화**였다

개정은 점을 문자로 허용하고 `.`·`..` 세그먼트만 거부한다. 그런데 **서버에서 `..` 가 되는
값은 `..` 만이 아니다.**

```
'..;a=b'  ->  /public/..;a=b/readme   Tomcat/Servlet: `;params` 제거 후 정규화 -> /readme
'.. '     ->  /public/.. /readme      IIS 계열: 세그먼트 끝 공백·점 제거      -> /readme
```

우리 눈에는 점만 든 평범한 값이고, `value_pattern` 이 앵커·fullmatch 라도 저자가
`^[A-Za-z0-9.;=]+$` 처럼 느슨하게 적으면 그대로 통과한다. `SEGMENT_FORBIDDEN` 이 존재하는
이유가 정확히 그것이다 — api_index.py 의 주석이 이미 `\` 에 대해 같은 논리를 적어 두었다:
**계약의 문언이 아니라 계약의 목적을 지킨다.** 같은 논리를 `;` 와 공백류에 적용했다.

- `;` → `SEGMENT_FORBIDDEN` 에 추가 (식별자 세그먼트에 필요한 경우가 없다)
- 공백류 → 문자 목록이 아니라 `any(ch.isspace() ...)` 술어로 검사 (탭·유니코드 공백까지)

**`...` 는 일부러 막지 않았다.** 어떤 서버도 이를 `..` 로 정규화하지 않는 평범한 이름이고,
"점이 들어 있으면 일단 막자"로 도망가면 개정을 되돌린 것과 같아진다. 그것을 지키는
테스트(`test_substitute_still_accepts_a_triple_dot_segment`)를 함께 넣었다.

SPEC 개정은 하지 않았다. 근거는 코드가 계약보다 **좁게** 동작하는 것은 계약 위반이
아니라는 것이다 — `;` 와 공백류는 AC-B-010-11 이 **허용한다고 적은 적 없는** 것을
추가로 막는 fail-closed 제약이고, 계약의 허용 집합을 넓히지 않는다.

> **정정 (라운드 8 LOW).** 이 자리에 원래 "`\` 가 AC-B-010-11 의 문자 목록에 없는데도
> 코드가 막는 선례" 라고 적혀 있었다. **사실이 아니다.** `docs/SPEC.md:190` 은
> `/`·`\`·`%`·`:`·`?`·`#` 를 명시적으로 열거한다 — 역슬래시는 처음부터 계약 안에
> 있었고, 그런 선례는 존재하지 않는다. `api_index.py` 의 같은 취지 주석도 함께
> 정정했다. 결론(개정 불필요)은 위의 실제 근거로 바뀌지 않지만, 없는 선례를
> 근거로 든 기록은 그 자체가 NG-10 위반이므로 지운다.

변이 2종으로 확인: `;` 제거 → 4종 red, 공백류 검사 무력화 → 3종 red.

### 14-2. MEDIUM — 양성 증거가 치환 결과를 구별하지 못한다 (deferred)

`ok2hop` 은 `attempts` 가 2건인지만 보고, **치환된 값이 실제 URL 에 반영됐는지**는 보지
않는다. 픽스처가 `/api/step2/` 접두만 검사해 아무 값이나 200 을 주기 때문이다.
codex 가 인메모리 변이로 실증했다 — `substitute()` 호출을 빼도 `ok=True`,
`phase0_attempts=2` 로 통과하고 `/api/step2/1.0.229` hit 은 0 이다.

최소 수정은 `assert_hits "/api/step2/1.0.229" "1"` 한 줄이지만 `us-b-010` 은 **동결 파일**이라
사용자 승인 재동결이 있어야 한다. 정책상 MEDIUM 은 완료 비차단이므로 **deferred 백로그**로
기록하고, 재동결 승인을 받는 다음 기회에 묶는다. 이 공백이 가리는 것은 "2-hop 이 도는가"가
아니라 "**점이 든 값이 URL 에 실제로 실렸는가**"다 — 전자는 단언되고 있다.

### 14-3. LOW — 증적 파일이 JSON 이 아니었다

`r2-crates-2hop-live-2026-09-01.json` 앞에 stderr 한 줄이 붙어 `json.load()` 가 깨졌다.
증적은 사람이 읽으라고 두는 것이 아니라 기계가 재검증하라고 두는 것이므로 고쳤다 —
stderr 는 같은 이름의 `.log` 로 분리했다. 파싱된 내용이 §13-3 의 서술과 일치한다:

```
phase0  https://crates.io/api/v1/crates/serde   200   success   rule=None
policy  original                                None  blocked   rule=redirect_hop
```

### 14-4. 라운드 상한 처리

수정 발생 라운드 예산(5)은 라운드 1~5 로 소진됐고, 라운드 7 에서 신규 HIGH 가 나왔다.
정책대로 `record-error --type REVIEW_ROUND_CAP --level L2` 를 기록해 review-escalation 을
트리거했다 (`count: 1, escalation: L2`). 승격 라운드는 상한 예외다.

### 14-5. 검증

- `pytest tests/unit -q` → **95 passed** (신규 7종, 변이 사멸 7건 실증)
- 변이 C(`;` 제거) → 4종 red / 변이 D(공백류 검사 무력화) → 3종 red


## 15. 라운드 8 — 에스컬레이션 2자 리뷰

수정 라운드 예산(5)이 소진된 뒤 라운드 7 이 신규 HIGH 를 냈으므로 `REVIEW_ROUND_CAP`
L2 를 기록하고 이 라운드를 **승격 라운드**로 돌렸다. 승격은 범위를 쪼갠 독립 2자다.

| pass | 범위 | 결과 |
|------|------|------|
| A | 프로덕션 보안 로직 (`substitute` 와 가드) | CRITICAL 0 / **HIGH 1** / MEDIUM 0 / LOW 0 |
| B | 계약·테스트 무결성·기록 정직성 | CRITICAL 0 / HIGH 0 / MEDIUM 2 / LOW 1 |

### 15-0. 라운드 7 항목 종결

pass B 는 `R2-R7-M1` 의 deferred 처리를 **절차상 정당하며 severity laundering 이 아니라고**
판정했다. 근거로 든 것은 무엇이 증명되지 않는지를 문서와 장부가 스스로 공개하고 있다는
점이다. 다만 같은 판정에서 이렇게 못 박았다 — **현재 동결 증거는 "2단계까지 갔다"와
단위 테스트의 치환 동작까지이고, "점이 든 값이 실제 전선에 실렸다"의 동결 E2E 증거는
아니다.** §13 의 `ok2hop` 서술은 그 범위로 좁혀 읽어야 한다.

### 15-1. HIGH — 값이 아니라 **보내는 것**을 검사해야 했다

라운드 7 에서 `;` 와 공백류를 막아 "값 단독" 정규화 우회는 닫혔다. pass A 가 찾은 것은
그 계열의 남은 절반이다. 값에는 `%` 가 없어도 **템플릿의 리터럴 `%`** 와 붙으면
퍼센트 시퀀스가 **합성된다**.

```
template = "https://api.example/public/%{hex}%2e/readme"
hex      = "2e"                       # `%` 없음 — 값 단위 검사는 통과한다
rendered = ".../public/%2e%2e/readme"
```

Tomcat 은 `%xx` 를 디코드한 **뒤** URI 를 정규화하므로 이를 `/readme` 로 처리한다.
우리가 robots 를 물어본 경로(`/public/%2e%2e/readme`)와 서버가 실제로 여는 경로
(`/readme`)가 갈라진다 — 응답이 우리를 같은 오리진의 **다른 경로**로 보내는 것이고,
AC-B-010-13("조립된 URL 도 robots 를 새로 통과해야 한다")이 무력화된다.

값 목록에 문자를 더 넣는 방식으로는 이 계열이 닫히지 않는다. **위험한 것은 값이 아니라
값과 리터럴이 만든 결과**이기 때문이다. 그래서 검사 대상을 바꿨다 — `_bad_path_segment()`
가 **렌더된 URL 의 경로 세그먼트**를 본다.

- **로드 시점** (`_check_request_template`): 치환자를 안전한 토큰으로 바꾼 뒤 같은 규칙을
  건다. 리터럴 `%` 가 치환자 옆에 있으면 인덱스 저자가 **로드에서** 실패를 본다.
- **요청 시점** (`substitute`): 치환 결과를 다시 본다. 로드가 이미 걸렀더라도 이중으로
  본다 — 값 검사를 이중으로 하는 것과 같은 이유다.

부수 효과로 같은 계열의 다른 절반도 함께 닫혔다: `"{x};a=b"` 템플릿에 `x="1.0"` 이라는
멀쩡한 값이 들어와 `1.0;a=b` 세그먼트를 만드는 경우다. 값 단위 검사만으로는 잡히지 않고
렌더된 세그먼트를 봐야 잡힌다.

pass A 가 함께 확인해 준 비발견 사항:

- `..%00`·`..%5c`·overlong UTF-8 은 값에 `%` 가 있어 이미 거부된다.
- `. .`·U+00A0(NBSP)는 `str.isspace()` 가 True 라 거부된다.
- U+200C(ZWNJ)는 `isspace()` 가 False 지만 이를 제거해 `..` 로 만드는 서버를 찾지 못했고,
  Phase 0 은 ASCII 로 요청을 보내므로 비ASCII 경로는 전송 전에 실패한다.
- `1.0.` (후행 점)은 IIS 가 점을 떼지만 `..` 가 되거나 상위로 탈출하지 않는다 — 보안이
  아니라 API 의미 문제다.
- `...` 을 `..` 로 바꾸는 서버는 확인되지 않았다. 계속 허용하는 판단은 방어 가능하다.
- `;` 차단으로 깨지는 출하 항목·동결 픽스처는 없다.

### 15-2. MEDIUM 2건 — 둘 다 즉시 고쳤다

**(1) `source` 가 https 전용이 아니었다.** SPEC:278 은 `https` URL 을 요구하는데 검증기는
`("http://", "https://")` 를 받고 있었다. `http://` 출처는 중간자가 바꿔 쓸 수 있어
"검증 가능한 주장"이 되지 못한다 — 계약대로 https 만 받도록 좁혔다. 출하 인덱스와 동결
픽스처의 `source` 는 전부 https 라 깨지는 것이 없다(확인 후 변경).

**(2) 요청 예산이 "정확히 3"인지 검증되지 않았다.** 동결 인수 테스트는 `/api/ep4 == 0`
만 보고 `/api/ep3 == 1` 은 보지 않았고, 단위 테스트의 산식은 `REQUEST_BUDGET` 자체를 다시
읽어 값이 바뀌어도 초록이었다 — 라운드 5 HIGH-2 와 같은 함정이다. `REQUEST_BUDGET == 3`
을 상수로 못 박고, 앞 둘이 404 고 **세 번째가 본문을 주는** 정상 항목으로 `ep1~ep3` 각
1회 · `ep4` 0회를 단언한다. 예산이 2 면 구제를 포기하고 4 면 쏘지 않기로 한 곳을 두드린다.

### 15-3. LOW — 없는 선례를 근거로 든 기록 (내 NG-10 위반)

§14-1 과 `api_index.py` 주석은 `;` 무개정의 근거로 "`\` 가 AC-B-010-11 의 문자 목록에
없는데도 코드가 막는 선례" 를 들었다. **사실이 아니다.** `docs/SPEC.md:190` 은
`/`·`\`·`%`·`:`·`?`·`#` 를 명시적으로 열거하고, 역슬래시는 처음부터 계약 안에 있었다.

결론(개정 불필요)은 바뀌지 않는다 — 실제 근거는 `;` 와 공백류가 계약이 **허용한다고 적은
적 없는** 것을 추가로 막는 fail-closed 제약이라 허용 집합을 넓히지 않는다는 것이다.
그러나 없는 선례를 근거로 든 서술 자체가 NG-10 위반이므로 문서와 주석 양쪽을 정정했다.
이런 종류가 위험한 이유는 후속 검토자가 그 문장을 근거 삼아 "기존 계약 밖의 좁은 구현"
이라는 분류를 재사용하기 때문이다 — 근거 없는 분류가 관행이 된다.

### 15-4. 동결 테스트가 못 하는 것을 단위 테스트로 옮겼다

`R2-R7-M1`(치환값이 실제 전선에 실렸는지 동결 테스트가 구별하지 못함)과 15-2(2)의 인수
테스트 절반은 둘 다 **동결 파일**이라 사용자 승인 재동결 없이는 손댈 수 없다. 그래서
백로그에 남겨 둔 채, **막는 것이 무엇인지**를 동결되지 않은 `tests/unit/` 으로 옮겼다.

- `test_chain_puts_the_substituted_value_on_the_wire` — 단위 픽스처는 `/step2/1.0.229`
  **정확히 그 경로만** 답한다. 동결 픽스처가 `/api/step2/` 아래 아무 경로나 답해서
  치환을 통째로 건너뛰어도 초록이던 그 공백이, 여기서는 빨개진다.
- `test_endpoints_budget_reaches_exactly_the_third` — 세 번째가 처음 본문을 주는 정상 항목.

이것이 재동결을 대신하지는 않는다. 동결의 목적은 "구현 Phase 가 인수 기준을 못 고치게
하는 것"이고 단위 테스트는 그 보호 밖에 있다. 다만 **아무 데서도 검증되지 않던 동작이
이제 검증된다** — 다음 재동결 승인 기회에 인수 테스트로 승격한다.

### 15-5. 검증

- `pytest tests/unit -q` → **103 passed** (라운드 7 의 95 에서 8 종 추가)
- `bash tests/acceptance/run.sh` → `ACCEPTANCE_RESULT: total=10 passed=10 failed=0` (동결 스위트 무손상)
- `shared-gate.sh acceptance-gate` → `total=10 passed=10 failed=0 (exit=0)` — 해시 무결성 포함 PASS
- `python -m open_reach.engine bench --battery bench/battery.yaml` → `rate=1.000 total=36 passed=36 failed=0`,
  `vendor_sc8: false_negative=0 false_positive=0 miss_rate=0.0`, `regression=none` — 라운드 7 과 동일, 회귀 없음

변이 5종을 주입해 각 테스트가 **지정한 변이를 실제로 죽이는지** 확인했다.

| 변이 | red 가 된 테스트 |
|------|------------------|
| E 로드 시점 세그먼트 검사 제거 | `test_template_cannot_synthesise_a_percent_sequence_at_load` |
| F 치환 후 세그먼트 검사 제거 | `..._percent_synthesised_by_the_template`, `..._semicolon_synthesised_by_the_template` |
| G `source` 를 http 허용으로 되돌리기 | `test_source_must_be_https` |
| H `REQUEST_BUDGET = 2` | `test_request_budget_value_is_pinned`, `test_endpoints_budget_reaches_exactly_the_third` |
| I `_run_chain` 의 `substitute()` 생략 | `test_chain_puts_the_substituted_value_on_the_wire` |

### 15-6. 남은 것

- `R2-R7-M1` (MEDIUM, deferred) — 동결 `ok2hop` 에 `assert_hits "/api/step2/1.0.229" "1"`.
- `R2-R8-M2-acc` (MEDIUM, deferred) — 동결 `us-b-010` 에 3번째 엔드포인트 성공 케이스와
  `assert_hits "/api/ep3" "1"`, 그리고 `source` 누락·`http://` 를 각각 exit 3 으로 단언.

둘 다 **사용자 승인 → `acceptance-freeze --approved-by-user`** 로만 닫을 수 있다. 정책상
MEDIUM 은 완료 비차단이고, 실질 동작은 15-4 의 단위 테스트가 이미 지키고 있다.
