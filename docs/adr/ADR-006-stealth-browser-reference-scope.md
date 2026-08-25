# ADR-006: stealth-browser에서 무엇을 가져오고 무엇을 배제하는가

- 상태: Accepted
- 날짜: 2026-08-25
- 관련: A8, NG-1, NG-3, NG-4, NG-5, NG-6, ADR-004
- 대상: `vp-k/stealth-browser` (private, TypeScript, 145 tests, 최종 푸시 2026-04-02)

## 맥락

같은 소유자의 기존 프로젝트 `stealth-browser`(이하 sb)는 표면적으로 같은 문제를 다룬다 —
"봇 탐지에 막힌 사이트에 접근한다". 재사용 가능한 부분이 있는지 검토했다.

검토 결과, **sb와 open-reach는 목적 함수가 다르다.**

| | stealth-browser | open-reach |
|---|---|---|
| 최적화 대상 | **탐지 점수** (BrowserLeaks/CreepJS 100/100) | **돌파율** (기대 정답 대조 통과율) |
| 신원 | seed 기반 **지속** 프로필 (warmup으로 신뢰도 축적) | **매 실행 폐기** (NG-4) |
| 로그인 콘텐츠 | Tier 3 Cookie Bridge로 **실제 브라우저 쿠키 주입** | **감지 후 중단** (NG-1) |
| 행동 | humanize (마우스·스크롤·타이핑 시뮬레이션) | 없음 |
| 프록시 | `--proxy` 지원 | 인터페이스 미제공 (NG-6) |
| 용례 | price-scraper, rank-tracker, multi-account 자동 로그인 | 단건 공개 콘텐츠 조회 (NG-5) |

sb는 **"탐지되지 않는 신원을 만드는 도구"** 이고, open-reach는
**"공개 콘텐츠에 도달했는지를 계측하는 도구"** 다. 코드를 공유할 수 없는 이유가 여기 있다.

## 결정

### 가져오는 것

| 대상 | sb 출처 | open-reach에서의 쓰임 |
|------|---------|----------------------|
| **차단 판별 휴리스틱** | `core/block-detector.ts` `isAccessBlocked()` — status 403/418/503, title `access denied\|just a moment\|attention required`, 짧은 본문 + 차단 키워드 | `validators.py`의 `waf_challenge` 신호. 단 sb는 blocked/ok 2분류이고 우리는 11종이므로 **분류를 세분화**해서 편입 |
| **CAPTCHA 감지 셀렉터** | `core/resilience.ts` `detectCaptcha()` — reCAPTCHA/hCaptcha/Cloudflare challenge 셀렉터 + title 마커 | **푸는 게 아니라 멈추기 위해** 쓴다 (NG-3). 감지 시 `waf_challenge`로 종결 |
| **지수 백오프 retry** | `core/resilience.ts` `retry()` — baseDelay × 2^attempt, maxDelay 상한 | 호스트별 rate limit 준수 (NG-6). `Retry-After` 우선, 없으면 이 곡선 |
| **GracefulShutdown (LIFO)** | `core/resilience.ts` | **NG-4 강제에 필수.** 임시 브라우저 프로필은 정상 종료뿐 아니라 크래시·SIGINT에서도 삭제돼야 한다. 등록 핸들러 LIFO 실행 패턴을 채택 |
| **원자적 파일 락** | `profile/manager.ts` (`openSync` `wx`) | `profiles.yaml` 갱신(`refresh`)과 관측 JSONL append의 원자성 |
| **지연 설치 + `info` 진단** | `sb setup` / `sb info` | SC-7(깨끗한 환경 설치 개입 0회). `open-reach doctor`가 런타임·엔진·의존성 상태를 한 번에 보고 |
| **3단 폴백의 경험적 타당성** | Tier1 fingerprint → Tier2 실제 Chrome(진짜 TLS) → Tier3 | ADR-004의 3단 구조를 **경험적으로 뒷받침**. 특히 "실제 Chrome 바이너리가 유효한 TLS/JA3를 준다"는 T2→T3 근거 |
| **측정 격리 교훈** | `code-review-result.md` ERR-HIGH-003 / DATA-HIGH-004 — `page.route` 미해제·`addInitScript` 잔존이 **다음 테스트를 오염**시킴 | `bench/run.py`는 **URL마다 완전 격리**해야 한다. 한 시도의 잔여 상태가 다음 URL의 측정을 바꾸면 돌파율 자체가 무효 |

인용은 **개념·휴리스틱 수준**이며 TypeScript 코드를 Python으로 옮겨 적지 않는다.
sb는 본인 소유 private 레포이므로 라이선스 제약은 없으나, open-reach는 공개 배포되므로
**출처를 코드 주석과 본 ADR에 남긴다.**

### 배제하는 것 (그리고 그 이유가 곧 A8 판정 기준이다)

| 배제 | 충돌 |
|------|------|
| `cookie-bridge.ts` + `extension/` — 사용자 실제 Chrome 쿠키 주입 | **NG-1 + NG-4 정면 위반.** sb의 Tier 3는 "로그인이 필요한 사이트"를 명시적 타깃으로 삼는다. 우리는 거기서 멈춘다 |
| `fingerprint.ts` — seed 기반 **지속** 신원 | NG-4. 우리는 매 실행 폐기 프로필을 쓴다. 지속 신원은 추적 가능한 가짜 정체성을 만드는 일이다 |
| `profile/warmup.ts` — 실제 사이트를 돌며 "프로필 신뢰도" 축적 | 가짜 열람 이력 제조. 경계 밖 |
| `humanize.ts` — 마우스·스크롤·타이핑 시뮬레이션 | **행동 위장.** "공개 콘텐츠 접근"이 아니라 "사람인 척하기"다 |
| `detect/score.ts` — BrowserLeaks/CreepJS 탐지 점수 | **지표가 틀렸다.** "얼마나 안 들키나"는 회피 지표이고, 우리 North Star는 "정답 대조를 통과했나"다 |
| `proxy.ts` / `--proxy` | NG-6 |
| `examples/multi-account.ts` (계정별 프로필 + 자동 로그인), `price-scraper*`, `rank-tracker` | NG-1, NG-5 |
| fingerprint-chromium 바이너리 | sb 자체 `CLAUDE.md`가 **"공급망 리스크 — 소스코드 1개월 지연 공개"** 로 경고. 공개 마켓플레이스 플러그인이 실을 수 없다 |

## 결과

**가장 큰 소득은 A8이 구체화된 것이다.**

초안의 A8("브라우저 사용이 봇 탐지 회피가 아니라 공개 콘텐츠 접근으로 정당화되는가")은
판정 기준이 없는 느낌표였다. sb를 대조군으로 놓으니 선이 그어진다:

> **A8 판정 기준** — 브라우저 티어가 다음 넷 중 **하나라도** 하면 "회피 도구"이며 T2/T3를 삭제한다.
> 1. 실행 간 **신원을 지속**시킨다 (프로필·쿠키·세션·지문 재사용)
> 2. **사람 행동을 흉내** 낸다 (마우스·스크롤·타이핑·체류시간 시뮬레이션)
> 3. **사용자의 자격증명·쿠키**를 읽거나 주입한다
> 4. 성공 지표가 **탐지 회피도**를 포함한다 (돌파율이 아닌 stealth score)
>
> 넷 다 아니면 "표준 브라우저로 공개 페이지를 여는 것"이며, 이는 사람이 직접 하는 일과 다르지 않다.

우리 브라우저 티어는 **임시 프로필 + 지문 위조 없음 + 행동 시뮬레이션 없음 + 쿠키 미취급**이다.
patchright를 쓰는 것은 `navigator.webdriver` 같은 **자동화 아티팩트를 제거**하기 위함이지
신원을 위조하기 위함이 아니다 — 이 구분이 유지되는 한 T2는 정당화된다.
유지되지 않는 방향의 변경(위 4항목 중 하나라도 도입)은 **본 ADR 위반**이다.

**나빠지는 것 / 감수하는 것**
- sb가 뚫는 것 중 우리가 못 뚫는 영역이 생긴다 (로그인 필요 사이트, 강한 행동 분석 WAF).
  → 그건 `auth_wall` / `waf_challenge`로 **정직하게 보고**한다. 돌파율이 낮아지는 것을 받아들인다 (P3).
- 두 도구가 겹쳐 보여 "왜 둘 다 있나"는 질문이 생긴다. → 본 ADR의 대조표가 답이다.

## 대안

- **sb를 확장해 open-reach를 그 위에 얹는다**: 기각. 목적 함수가 반대라 경계를 강제할 수 없고,
  cookie-bridge·warmup·proxy가 의존성에 남는 순간 NG-1/4/6이 선언으로 전락한다 (P7).
- **sb의 브라우저 계층만 라이브러리로 추출해 공유**: 기각. 지속 프로필·지문 위조가 그 계층의 핵심이라
  떼어내면 남는 것이 Playwright 얇은 래퍼뿐이다.
