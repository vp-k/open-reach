---
name: open-reach
description: "리서치 중 공개 웹 소스가 표준 fetch(WebFetch/curl)로 막혔을 때(403·WAF 챌린지·봇 차단) 사용한다. 정책상 허용되는 공개 접근 경로를 순서대로 시도하고, 성공하면 본문 마크다운을, 실패하면 분류된 사유와 시도 이력을 남긴다. 질의로 공개 검색 소스에 팬아웃하는 `search`, 명시한 URL 목록을 병렬 취득하는 `fetch --batch` 포함(재귀 링크 추적 없음). 로그인월·페이월은 돌파하지 않고 감지·보고만 한다. 인증 우회·CAPTCHA 해결·프록시 로테이션·신원 위장 없음. SSRF는 fail-closed로 차단. robots.txt는 v2.0.0부터 기본 미조회이며 `--respect-robots`로 준수를 켠다."
---

# open-reach

**공개 웹 문서를 정직하게 가져오거나, 왜 못 가져왔는지 분류해 보고한다.**

리서치의 근거가 "실제로 중요한 소스"가 아니라 "우연히 열리는 소스"로 좁혀지는 편향을 막는 도구다.
표준 fetch가 막힌 공개 소스에 대해 정책상 허용되는 접근 경로를 순서대로 시도하고, 결과·한계·근거를
재현 가능하게 남긴다.

## 언제 쓰나

리서치 도중 다음 신호가 보이면 이 스킬을 쓴다:

- WebFetch/curl 이 **403 / 429 / 503** 을 반환하거나 빈 본문·챌린지 페이지를 준다
- Cloudflare·Akamai·DataDome 등 **WAF 챌린지**(JS challenge, "Checking your browser")가 보인다
- 같은 공개 글이 브라우저로는 열리는데 도구로는 안 열린다

**쓰지 않는 경우:** 로그인·구독이 필요한 콘텐츠(페이월/로그인월). open-reach 는 이런 벽을 **돌파하지
않는다** — 감지해서 `paywall`/`auth_wall` 로 분류·보고만 한다(종료코드 2).

## 사용법

플러그인 루트 기준 스킬 디렉터리에서 실행한다(순수 표준 라이브러리, 외부 의존성 없음):

```bash
cd "${CLAUDE_PLUGIN_ROOT}/skills/open-reach"
python -m open_reach.engine fetch "<URL>"
```

`curl_cffi` 가 설치돼 있으면 브라우저 TLS 지문 임퍼소네이션을 추가로 쓰지만, 없어도 표준 클라이언트로
동작한다(설치 개입 0회 — P2 계약). 성공하면 본문 마크다운을 stdout 으로, 실패하면 분류된 실패 사유와
시도 이력(attempts)을 낸다.

`--allow-browser` 를 주면, HTTP 티어(T1)가 JS 챌린지에 막힐 때만 지연 설치 브라우저 티어(T2 ·
patchright + Chromium)로 폴백해 HTML 을 실제로 렌더한 뒤 공개 본문을 취득한다. patchright 미설치
환경에서는 그 사실을 `browser_disabled` 사유로 강등할 뿐 없는 돌파를 지어내지 않는다(NG-10). 이
티어는 매 호출 임시 프로필을 쓰고 지문 위조·행동 시뮬·쿠키 취급을 하지 않는다(A8 준수 — ADR-006).

HTTP 티어가 본문을 못 얻으면 **Phase 0 공개 API 라우팅**이 개입한다(R5): 출하 인덱스
(`engine/api_index.yaml`)에 실측·출처가 기록된 호스트 — Hacker News(`/item?id=N` → Algolia items
API), Bluesky(`/profile/{handle}/post/{rkey}` → 공개 XRPC) — 는 플랫폼이 스스로 공개한 JSON
엔드포인트로 같은 본문을 가져온다. 인덱스에 없는 호스트는 시도하지 않는다(URL 추측 금지). 또한
사용자가 **검색 URL 을 직접 입력**한 경우(선언된 검색 엔드포인트: hn.algolia.com)는 결과 목록을
본문으로 인정한다 — 면제는 nav_shell 판정 하나뿐이고 길이 하한·챌린지 판별은 그대로다(US-B-014).

HTTP 티어가 **바이트는 받았는데 본문이 못 쓸 때**(JS 셸·내비게이션 셸), Phase 0 앞에서
**자기선언 열린문 티어**가 개입한다(R6): 받은 HTML 이 스스로 선언한 대체 표현만 따라간다 —
JSON-LD `articleBody`(요청 없이 즉시 본문), RSS/Atom `<link rel=alternate>`, `amphtml`,
JSON oEmbed, 다른 오리진의 `canonical`. **선언이 없으면 요청을 만들지 않는다** — `m.` 접두를
붙여 보는 식의 URL 추측은 하지 않는다(R2 실측 0/12, NG-10).

### 검색 (질의 → 후보 → 병렬 취득)

```bash
python -m open_reach.engine search "<질의>" --max-results 10
python -m open_reach.engine search "<질의>" --urls-only        # 후보만, 취득 안 함
python -m open_reach.engine search "<질의>" --sources ddg,hn
```

인덱스의 `search_sources:` 에 **정직한 UA 로 200 을 직접 실측한** 공개 검색 소스만 등재돼 있다
(ddg lite · HN Algolia · StackExchange · GitHub · Wikipedia · Crossref · OpenAlex). 소스에 병렬로
물어 후보를 라운드로빈으로 섞고, dedupe 후 `--max-results`(기본 10 · 상한 25)로 자른 다음 배치로
가져온다. 출력은 NDJSON 이고 **첫 줄이 검색 요약**(소스별 성패 + 후보 목록)이다.

**취득한 본문의 링크를 다시 후보로 넣지 않는다.** 이것이 이 도구가 크롤러가 되지 않는 유일한
방벽이라(NG-5 개정판), 후보를 만드는 모듈은 취득 경로를 임포트조차 하지 않는다.

**엔진 밖 경로 — 대개 이쪽이 더 강하다.** Claude 의 `WebSearch` 로 후보를 모아 파이프로 넘기면
의존성·키 0으로 가장 넓은 검색과 이 도구의 돌파력을 합칠 수 있다:

```bash
printf '%s\n' "$URL1" "$URL2" "$URL3" | python -m open_reach.engine fetch --batch -
```

### 서브커맨드

| 명령 | 용도 |
|------|------|
| `fetch <url>` | 한 URL 을 가져온다. `--intent article\|media\|raw`, `--timeout`, `--allow-browser` |
| `fetch --batch <파일\|->` | 명시한 URL 목록(상한 50)을 병렬 취득. `--concurrency N`(기본 4·상한 8). URL 당 NDJSON 한 줄 |
| `search "<질의>"` | 질의로 후보 URL 을 모아 배치 취득. `--urls-only`, `--sources`, `--max-results` |
| `explain <url>` | 실제 요청 없이 정책 판정(허용/차단·사유)만 미리 본다 |
| `bench --tier 1\|2` | 벤치 배터리로 돌파율을 계측한다 |
| `compare` | 원본(insane-search 등)과 돌파율을 대조한다 |
| `baseline <sample>` | 표준 fetch 기준선 실패율을 측정한다(A0 중단 판정 근거) |
| `refresh` | 관측(observations)에서 WAF 프로필을 갱신한다 |

### 종료코드

| 코드 | 의미 | 해석 |
|------|------|------|
| 0 | 성공 | 본문 확보 |
| 1 | 실패 | 네트워크·검증·not_found 등 — 재시도/대체 소스 검토 |
| 2 | 경계 | `auth_wall`/`paywall`/`policy_blocked` — **정책상 접근 불가**, 돌파 금지 |
| 3 | 게이트 | 벤치 SC 위반 등 계측 게이트 실패 |
| 4 | 사용법 오류 | 인자 오류 |

종료코드 2 는 "못 뚫었다"가 아니라 **"뚫지 않기로 한 경계"**다. 이 결과가 나오면 그대로 사용자에게
"이 소스는 로그인/구독이 필요해 공개 접근 대상이 아니다"라고 보고하고, 대체 공개 소스를 찾는다.

## 경계 (NG-1 ~ NG-13, 완화 금지)

이 도구는 **공개 콘텐츠만** 취급한다. 다음은 코드의 정책 계층에서 fail-closed 로 강제된다:

- 로그인월·페이월 **미돌파**(401 포함, 감지·보고만)
- 인증 우회 없음 · CAPTCHA 해결 없음 · 프록시 로테이션 없음
- 지속 신원·행동 위장 없음 · rate limit 존중(호스트당 동시성 1 + 최소 간격 1.0초 — 배치·검색에서도 동일)
- **SSRF 차단**: 사설 IP·루프백·메타데이터 엔드포인트 접근 금지(fail-closed)
- 취득 본문을 디스크에 보관하지 않음

경계를 넓히려면 `docs/overview.md`(헌법)와 `docs/SPEC.md` 를 먼저 고쳐야 한다. 코드가 임의로 벽을
넘지 않는다.

### robots.txt — v2.0.0 부터 기본 미조회

v1.x 는 robots.txt 를 fail-closed 로 준수했다. v2.0.0 은 **기본값이 `off`**(조회하지 않음)다.
이것은 사용자가 명시적으로 선택한 방침이며, 그 대가를 여기 적어 둔다: **사이트가 명시한 AI/RAG
접근 거부 의사를 알고도 지나간다.** robots 는 법이 아니지만 의사 표시이고, 이 도구는 그것을
"윤리 경계"로 내세우지 않는다.

| 모드 | 동작 |
|------|------|
| `--robots off` (기본) | 조회하지 않는다. 오리진당 요청 1회 감소 |
| `--robots advisory` | 조회해 판정을 남기되 차단하지 않는다. `Crawl-delay` 는 계속 반영한다 |
| `--respect-robots` (= `enforce`) | v1.x 동작. Disallow 면 `policy_blocked` 로 차단 |

바뀌지 않은 것: 로그인월·페이월 미돌파, 신원 위장 금지(허용 UA 참칭도 하지 않는다), 프록시
로테이션 금지, SSRF fail-closed, 호스트당 최소 간격. robots 를 안 보는 것과 신원을 속이는 것은
다른 일이다.

## 근거·설계 문서

- `docs/overview.md` — 문제 정의·Non-Goals(헌법)
- `docs/SPEC.md` — 데이터 모델·인수 기준(AC)·실패 사유 분류
- `docs/adr/` — 주요 결정(ADR-005 build-vs-depend 등)
- `docs/policy-boundaries.md` — NG-1~NG-13 상세
