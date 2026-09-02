# R3 계약 — 브라우저 티어를 '넣되 회피 도구로 만들지 않는다'

- **작성일**: 2026-09-02
- **지위**: SPEC「Round 경계」의 `R3` 행(§566-567)은 *브라우저 티어(A8 4항 판정 통과 시에만) ·
  경로 재사용 우선순위 · `refresh` · holdout · 설치 시험 · SKILL.md 패키징*을 나열한다.
  이 문서가 그 확정안이며, R2 계약(`docs/r2-contract.md`)이 R3로 미뤄 둔 SC-2/6/7/8의
  마무리를 함께 못박는다.
- **SPEC은 동결돼 있다**(`docs/SPEC.md`). 이 문서는 계약(개정안)이며, 승인 없이 SPEC 본문을
  고치지 않는다. SPEC 대비 사실이 바뀐 두 줄(§41 "브라우저 티어는 지연 설치 대상",
  §216 allow_browser "R1에서는 항상 false로 강제")의 갱신 필요는 §8에 적는다.
- **사용자 결정**: ① 브라우저 폴백 = 전 단계 허용, Must→Should + **A8 게이트** ②
  crates.io readme = **Q1 현행 유지**(Phase-0 same-origin 유지) ③ 벤더 미확보 표본 =
  AC-B-009-3 처분(지어내지 않음) ④ "브라우저 티어까지 한 번에 풀 R3"(설치→구현→검증→
  인수 테스트→재동결→holdout).
- **근거**: `bench/evidence/r3-browser-vendor-probe.json`(오늘 라이브) ·
  `tests/acceptance/us-b-011-browser-tier.sh`(동결) · `tests/unit/test_browser_tier.py`(11종) ·
  `bench/battery.yaml`의 `vendor_scope_reason` · `docs/adr/ADR-004`·`ADR-006` ·
  `docs/policy-boundaries.md §4`.

---

## 1. A8 판정 — 브라우저 티어의 '존재 자격'

ADR-006·policy-boundaries §4는 브라우저 티어가 아래 넷 중 **하나라도** 하면 그것은
'회피 도구'이며 **삭제 대상**이라고 못박는다. 이 판정을 통과하지 못하면 티어를 넣지 않는다.

| 항목 | 규칙 | 판정 방법 | 결과 |
|---|---|---|---|
| **A8-1** | 실행 간 신원 지속(쿠키·프로필·스토리지 재사용) 금지 | 소스 검사 + 2회 실행 후 프로필 잔존 카운트 | **PASS** — 매 호출 `tempfile.mkdtemp` 임시 프로필, LIFO 정리로 정상·예외·시그널 모두 삭제. 2회 실행 잔존 0(`test_fetch_twice_leaves_no_residue`) |
| **A8-2** | 사람 행동 흉내(마우스·타이핑·스크롤) 금지 | 소스 검사 | **PASS** — `page.goto` 후 `networkidle` **대기**만. 포인터·키보드·스크롤 API 호출 0 |
| **A8-3** | 자격증명·쿠키 취급 금지 | 소스 검사 + CLI/환경변수 | **PASS** — 쿠키/세션/storage_state 옵션 없음. 임시 프로필 쿠키는 프로필과 함께 소멸 |
| **A8-4** | 성공 지표에 탐지 회피도 금지 | bench 출력 필드 | **PASS** — 성공은 '공개 본문 취득'으로만 판정. bench에 회피도 필드 없음 |

patchright는 `navigator.webdriver` 등 자동화 아티팩트를 **제거**할 뿐 지문을 **위조**하지
않는다 — ADR-006이 명시적으로 허용한 범위다. **판정: 4항 전부 PASS → 티어 존재 승인.**

---

## 2. 브라우저 티어 설계 (ADR-004)

**티어 순서**: T1 `curl_cffi`(현행 HTTP 티어) → **T2 `patchright`(신설)** → T3 Playwright+실 Chrome(미구현, 필요 근거 없음).

**오르는 조건 (fetcher `_browser_worthy`)**: `allow_browser=True` **그리고** HTTP·Phase 0가
아래로 막힌 뒤에만.
- `waf_challenge` — JS 챌린지(Just a moment / challenge-running 등).
- `validation_failed` **AND** 신호에 `js_shell` — "JS를 켜라"는 셸만 온 경우.
- `empty_body`·`nav_shell`은 **오르지 않는다** — 브라우저로도 본문이 없다(SPA 무한대기 회피).

**판정 일관성**: `browser_fetch`는 성공/차단을 스스로 판정하지 않고 `status·html·final_url`을
그대로 넘겨, fetcher가 HTTP 티어와 **동일한 `detect.classify`**로 판정한다. 경로만 다를 뿐
합격 기준은 같다.

**경계 재검사 (NG-11)**: 브라우저가 리디렉션으로 옮겨간 `final_url`을 `policy.check_url`로
다시 검사한다. 사설 IP·루프백·메타데이터로 옮겨갔으면 `policy_blocked`로 떨군다. 인수
테스트 us-b-011이 로그인월을 `--allow-browser`로도 브라우저에 넘기지 않음을 검증한다.

**지연 설치 (SC-7)**: `patchright` import는 `browser.py` **함수 안에서만** 일어난다. T1
경로는 이 모듈을 import하지 않는다. 미설치 시 `browser_available()`이 `(False, 사유)`를
돌려주고 fetcher는 `browser_disabled` 정책 사유로 강등한다 — **없는 돌파를 지어내지
않는다(NG-10)**.

---

## 3. 정직한 라이브 소견 — "개입하되 풀지 않는다"

브라우저 티어를 실세계 하드-WAF 4벤더 대표 URL에 걸었다(`r3-browser-vendor-probe.json`).

| 벤더 | URL | 결과 | 읽는 법 |
|---|---|---|---|
| perimeterx | zillow.com/homes/ | `policy_blocked`/robots (route: policy) | robots 경계 — 브라우저까지 **가지도 않는다** |
| aws_waf | imdb.com/chart/top/ | `policy_blocked`/robots (route: policy) | robots 경계 — 동일 |
| kasada | canadagoose.com | `rate_limited` (route: http×4) | 429 — 브라우저 대상 아님(존중) |
| **f5** | **aa.com/homePage.do** | **`waf_challenge`, route: http×5 → browser, md_len 0** | **티어가 실제로 개입**했다. 렌더했으나 챌린지가 **스스로 풀리지 않아** md 0으로 **정직하게 waf_challenge 보고** |

**결론**: 브라우저 티어는 진짜 JS 챌린지에서 **올바르게 개입**한다(f5 aa.com이 증거).
그러나 **실세계 신규 돌파는 만들어 내지 않는다**. 이유는 셋이고, 셋 다 설계의 귀결이다.
1. 공개 콘텐츠는 대개 이미 T1 임퍼소네이션으로 뚫린다(R1 60/70).
2. 하드 WAF 챌린지(f5 등)는 챌린지를 **풀어야** 넘는데, 그것은 우리가 거부한다(NG-3·A8).
   우리는 렌더하고 md_len 0으로 **정직하게 waf_challenge를 보고**한다.
3. 조용한 SPA(twitch/united/notion)는 `nav_shell`/`empty_body`로 분류되며, **일부러**
   브라우저로 올리지 않는다.

이 소견이 브라우저 티어의 **입증된 가치**를 규정한다: (가) 결정적 픽스처 케이스(온-로드
자기 렌더, 풀이 없음) — us-b-011로 동결, (나) 진짜 챌린지에서의 **개입 증명 + 정직한
실패 보고**. "회피 성공"이 아니라 "경계 안에서의 정직"이 이 티어의 성공 정의다.

---

## 4. 벤더 표본 처분 (AC-B-009-3)

라이브 소견의 직접 귀결: **perimeterx·kasada·f5·aws_waf는 robots 허용 + 자기 해소
돌파 표본을 공급하지 못한다.** perimeterx/aws_waf 대표는 robots 경계, kasada는 rate
limit, f5는 풀어야만 넘는 챌린지다. 따라서 이 4종을 배터리에 넣으면 SC-2를 회귀시키거나
(자기 해소 안 됨) 경계를 넘어야 한다(robots).

**처분**: AC-B-009-3대로 **`vendor_scope`에 넣지 않고 `vendor_scope_reason`에 실측 건수를
남긴다**(이미 기록됨: `aws_waf 1 · perimeterx 0 · kasada 0 · f5 0`). 기준(G-1, 신뢰도 1.0
지목 ≥2건)은 낮추지 않았다. SC-2는 확보된 5종(cloudflare·akamai·datadome·imperva·fastly)
범위에서 판정한다. **감지기(profiles.yaml)는 9종 전부 유효**하다 — 미확보는 '감지 실패'가
아니라 '배터리 표본 부재'이며, 감지 정확도는 R2에서 신뢰도 1.0으로 검증됐다(SC-8).

---

## 5. crates.io readme 처분 (Q1: 현행 유지)

`/api/v1/crates/{name}/{version}/readme`는 **문서화된 same-origin** 엔드포인트다. 도달
불가가 아니라 **일반 HTTP 티어의 몫**이다(302를 hop별 SSRF·robots 재검사로 따라간다).
`api_index.yaml`의 Phase-0 인덱스에 **넣지 않는** 이유는 둘: ㉠ readme API를 인덱스에
넣으면 체인이 origin을 벗어난다(AC-B-010-12는 Phase-0 인덱스 체인에만 적용) ㉡
`static.crates.io` 리터럴은 공식 문서에 없다(AC-B-010-15 출처 의무). Phase-0 same-origin은
설계 결정이며(Q1 현행 유지), 이 처분은 **행동 무변경 주석**으로만 반영했다(engine/api_index.yaml).

---

## 6. SC 최종 판정 배치

| SC | 기준 | 상태 |
|---|---|---|
| **SC-2** | Tier-1 배터리 돌파율 3회 중앙값 `≥80%` AND 벤더별 `≥50%` | **PASS**(R2 실측: rate_median 1.0, 확보 5벤더 각 ≥50%). 범위는 §4 처분대로 |
| **SC-5** | `refresh` 1회 diff = 수동편집 0 AND 경계위반 학습 0 | **PASS**. `refresh --dry-run`(관측 1991건) diff 전부 기계 생성(observed_success 집계·last_reviewed·근거 재정렬), profiles.yaml 불변. 경계위반 학습 0(관측은 outcome=success만 적재, `_evidence`가 재필터, imperva 학습 성공 0). 증적 `bench/evidence/r3-sc5-refresh-dryrun.txt` |
| **SC-6** | holdout 배터리 돌파율, Tier-1 대비 낙폭 `≤15%p` | **PASS**(최종 코드 1회 실행, `bench/holdout.yaml`, dev-run 없음). holdout rate **1.000**(24/24) vs battery rate_median **1.0** → 낙폭 **0%p**. §6.1 참조 |
| **SC-7** | 새 환경 설치→첫 fetch 사람 개입 `0회`(T1 경로) | **PASS**. curl_cffi·patchright 둘 다 차단(바닥 stdlib-only)한 최초 fetch가 T1 HTTP로 성공(docs.python.org 25138자), 프롬프트 0·pip 개입 0, 브라우저 부재는 강등. 패키지 전역 `input()` 0곳. 증적 `bench/evidence/r3-sc7-install.json` |
| **SC-8** | 벤더 감지 오탐 0 AND 미탐 `≤10%` | **PASS**(R2). 브라우저 경로도 동일 `waf_verdict`를 거친다 |

### 6.1 SC-6 holdout 실측 (과적합 판정)

`bench/holdout.yaml`은 **개발·튜닝에 한 번도 쓰지 않은** 신규 도메인만 모은 보류 집합이다.
battery 의 18개 등록가능도메인과 disjoint 하고, 선정 방법론(감지기 신뢰도 1.0 지목)은
battery 와 동일하다. battery 양성의 지배 두 벤더(cloudflare 4·akamai 4 = 12건 중 8건)를
정확히 복제했다 — fastly·datadome 은 r2 재실측에 battery 밖 신뢰도 1.0 본문취득 후보가
각 1·0건뿐이라 양성 2건 하한을 채울 수 없어, 없는 후보를 추측으로 만들지 않고(NG-10)
채울 수 있는 두 벤더만 선언했다(G-8, `vendor_scope_reason`).

- 실행: `python -m open_reach.engine bench --holdout --runs 3` (최종 코드, dev-run 없음).
- 결과: **rate 1.000 (24/24)**, 음성 3건 전부 정분류(비게이팅), SC-8 clean(miss 0·오탐 0).
  전 도메인 T1(HTTP) 돌파 — 브라우저 티어 불요. 증적 `bench/evidence/r3-holdout-sc6.txt`.
- 판정: battery `rate_median 1.0` − holdout `1.0` = **낙폭 0%p ≤ 15%p** → PASS(dead-band 3%p 내).
- 주: `ho-cf-002`(epicgames)은 store 서브도메인 리디렉션으로 **벤더 귀속**만 unresolved 다.
  돌파 자체는 성립(min_chars 충족·passed 계상)하고 SC-8·게이트에 영향 없다.

---

## 7. 검증 자산 (이번 R3에서 추가)

- `skills/open-reach/open_reach/browser.py` — T2 티어(A8 준수).
- `skills/open-reach/open_reach/fetcher.py` — 브라우저 에스컬레이션 배선(`_browser_worthy`,
  `last_signals`, NG-11 재검사, `browser_disabled` 강등).
- `tests/acceptance/us-b-011-browser-tier.sh` — 동결. 미설치=강등, 설치=렌더 돌파 양분기.
- `tests/acceptance/fixture_server.py` — `/waf/js-challenge` 라우트(온-로드 자기 렌더).
- `tests/unit/test_browser_tier.py` — 17종(A8-1 잔존 0, LIFO 정리, 미설치 강등, 렌더,
  예외 격리(M1), 그리고 `_ssrf_allow` 5종: 비네트워크 스킴 통과·루프백/메타데이터 차단·
  공개 허용·DNS실패 fail-closed).
- `bench/holdout.yaml` — SC-6 보류 배터리(role: production, battery 와 disjoint, cf 4·ak 4 양성 + cf 2·ak 1 음성). §6.1.
- `bench/evidence/r3-holdout-sc6.txt` — SC-6 실측(rate 1.000, 24/24, 낙폭 0%p).
- 재동결: `.manifest.json` 14파일 + SPEC 해시, `--approved-by-user`.

---

## 7.5 코드 리뷰(codex 2자) 결과 및 수정

개발 싸이클(구현 → 리뷰 → 수정)에 따라 Claude(자체) + codex 2자로 브라우저 티어를
리뷰했다. Claude 측이 사전에 **M1**(browser_fetch 예외 전파 → CLI 크래시·attempts 유실)을
독립 발견·수정했고, codex가 아래 3건을 추가 지적했다. **셋 다 근본 수정 + 회귀 테스트**로
반영했다(임시 방편 없음).

| ID | 심각도 | 지적 | 수정 |
|----|--------|------|------|
| **C1** | Critical | NG-11 사후 `final_url` 검사는 공개→**사설**→공개 리디렉션의 중간 홉을 놓친다 — 브라우저가 사설 대상에 이미 연결 | `context.route("**/*")` **프리엠티브 SSRF 가드** 신설: 매 요청을 `_ssrf_allow`로 사전 판정, 사설이면 **연결 전 `route.abort()`**. 순수 함수로 추출해 브라우저 없이 회귀 테스트. A8 무침해(회피 아닌 경계 강제) |
| **H1** | High | `SIGTERM` 핸들러가 기본 동작(SIG_DFL) 복구를 안 해 정리 후 **프로세스가 종료 안 됨**(SIGTERM 삼킴) | 정리 후 기본 핸들러 복구 + `os.kill`(폴백 `SystemExit(128+sig)`)로 실제 종료. SIG_IGN은 존중 |
| **H2** | High | `timeout_s`가 `goto`에만 걸려 `networkidle`가 항상 4초 추가·`content()`/`close()` 무기한 블로킹 여지 | `context.set_default_timeout(nav_ms)` + `networkidle` 대기를 **잔여 예산으로 스케일**(min 500ms) |

추가로 Claude 측이 codex와 별개로, NG-11 **사후** 재검사의 `UnresolvableHost→통과`
fail-open을 발견해 **fail-closed**(private_range 차단)로 정정 — 코드베이스 전역
(hop_check·robots 프리체크)의 DNS-실패 관례와 일치시켰다. 사후 검사는 route 가드에 이은
2차 방어로 유지한다.

검증: 단위 148종 + 인수 11/11 통과(설치된 실제 Chromium 기준, us-b-011 설치 분기가
route 가드의 픽스처 오리진 예외 경로까지 실측).

---

## 8. SPEC 갱신(승인·반영 완료 — 2026-09-02)

브라우저 티어 구현으로 사실이 바뀐 SPEC 두 줄을 **사용자 승인** 하 반영하고 재동결했다.
- §41 "Playwright / patchright는 미설치 — 브라우저 티어는 **지연 설치 대상**" → **변경 없음**
  (지연 설치 계약은 그대로다. 사실 유지이므로 문구 조정 불요).
- §216 `allow_browser` "**R1에서는** 항상 false로 강제" → **반영됨**:
  "R1·R2에서는 `false` 강제, R3부터 `--allow-browser`로 opt-in".

**재동결**: `acceptance-freeze --approved-by-user` 실행. SPEC 해시
`d80666c5…` → `0c474d29…`로 갱신(14파일 해시는 불변). 세탁이 아니라 승인된 계약 반영이다.
