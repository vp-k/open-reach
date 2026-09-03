# R6 계약 — robots 정책 모드화 + 검색 계층 (open-reach v2.0.0)

라운드 R6. 사용자 요구: "insane search 만큼의 강력한 서칭을 할 수 있도록 수단과 방법을 따지지
말고 실행할 수 있도록 기획" (2026-09-02).

---

## §1 배경 — 잔여 격차의 실체

`docs/r1-report.md` 의 70 URL 배터리에서 원본 `fivetaku/insane-search` 64/70, open-reach
60/70. 격차 4건의 내역은 **robots 자발 포기 2건**(`www.reddit.com`, `www.linkedin.com`) +
성공 정의 차이 2건이었고, **실제 돌파력 격차는 0건**이었다. R5 가 노린 어댑터 후보
(네이버 통합검색 · Reddit `.rss` · Jina Reader) 도 셋 다 `User-agent: *` 전면 Disallow 라
미등재로 끝났다(`docs/r5-contract.md` §9).

즉 R5 의 파리티 시도를 막은 것은 우리 코드가 아니라 우리 정책이었다.

## §2 사용자 결정 (2026-09-02, AskUserQuestion)

- **robots.txt 전면 미준수** — 사용자 원문: *"insane-search와 동일하게 robots를 조회하지
  않는다. `--respect-robots` 플래그로만 켬. 도달력은 최대지만, 사이트가 명시한 AI/RAG 접근
  거부까지 무시하게 되어 문서상 '윤리 경계' 선언이 사라진다."* (권고했던 중간안을 명시적으로
  기각한 선택이다.)
- **도달력 레버 3종** — 자기선언 열린문 일반화 / 검색 계층 신설(질의→URL) / 병렬 배치 +
  본문 추출 품질. **아카이브 티어(Wayback CDX)는 선택되지 않았다** → R7 이월.

## §3 넘지 않은 선

경계 완화는 robots **하나뿐**이다. NG-1~NG-4 · NG-6 · NG-10~NG-13 은 강제 지점 무변경
(`docs/policy-boundaries.md` §2 배선표). 특히 **허용 UA 참칭은 하지 않는다** — robots 를
안 보는 것과 신원을 속이는 것은 다른 일이고, 후자는 NG-13 이다. 이 구분이 US-B-013
(Jina Reader) 철회를 R6 에서도 유지시킨다.

---

## §4 W1 실측 — robots 3 모드 (완료)

`off`(기본) / `advisory` / `enforce`(`--respect-robots`).

설계상 핵심은 **"무시"가 아니라 "미조회"** 라는 것이다. `policy.hop_guard_for("off")` 는
robots 코드 경로가 **없는** 가드(`ssrf_hop_guard`)를 돌려주므로, `off` 에서 robots 판정이
"내려졌다가 무시되는" 중간 상태 자체가 존재하지 않는다. 오리진당 요청 1 회가 줄어 지연도
감소한다.

사실/정책 분리: `robots_verdict` 는 robots.txt 가 무엇을 말하는지만 답하고, `robots_gate`
가 차단 여부를 결정한다.

**모순 입력은 조용히 해석하지 않는다** — `--robots off --respect-robots` 는 요청이 나가기
전에 exit 4 로 거절된다. 모호한 입력을 어느 한쪽으로 조용히 해석하는 것이 robots 에서는
가장 나쁜 실패다.

검증: 유닛 `test_robots_modes.py` 11 종, 동결 인수 `us-b-003`·`us-b-010` **양방향 고정**
(사용자 결정 2026-09-03: 단언 삭제가 아니라 반전 — `off` 에서 `/robots.txt` 히트 0,
`--respect-robots` 에서 R5 차단 정확 복원). 재동결 `--approved-by-user` 완료
(`refreezeHistory` 2 건 보존).

### ⚠ Crawl-delay 정정

기획 시점 계획서와 `policy-boundaries.md` §5 에는 "robots 의 `Crawl-delay` 가 호스트 간격
하한을 올린다" 고 적혀 있었으나, **그 동작은 코드에 구현된 적이 없다**. grep 결과 문서
1 줄에만 존재했다. 문서만의 주장이었으므로 삭제했다. 따라서 `off` 전환으로 잃는 간격
신호도 없다. 호스트당 동시성 1 과 `MIN_HOST_INTERVAL_S=1.0` 은 그대로 유지된다.

---

## §5 W2 실측 — robots 로 막혔던 어댑터 재평가 (완료, **신규 등재 0 건**)

측정 방법: 프로젝트 자신의 정직한 UA(`open-reach/… (+https://github.com/vp-k/open-reach)`)
로 직접 요청. 증적 `bench/evidence/r6-adapter-probe-2026-09-03.json`,
`r6-adapter-probe2-2026-09-03.json`.

AC-B-012-6 R6 개정 기준: 등재 조건은 robots 가 아니라 **정직한 UA 200 실측 + `source` +
`verified_at`**. robots 는 더 이상 등재 조건이 아니지만, **200 을 실측하지 못한 호스트는
여전히 미등재**다.

| 후보 | 실측 | 판정 | 사유 |
|------|------|------|------|
| `www.linkedin.com/company/…` | **200**, 335 KB → 본문 **11,105 자** | **어댑터 불요** | robots 를 안 보게 되자 **평범한 T1 HTTP 티어에서 그냥 열린다**. Phase 0 는 HTTP 실패 시의 폴백이므로 등재할 이유가 없다. R1 격차 2 건 중 1 건이 **인덱스 항목 없이** 닫혔다 |
| `www.reddit.com` `{permalink}.rss` | **429** (2 회, 간격 두고) | **미등재** | 200 미실측. 429 는 차단이 아니라 rate limit 이지만, 우리는 재시도로 밀어붙이지 않는다. 없는 성공을 지어내지 않는다(NG-10) |
| `www.reddit.com/r/{sub}.rss` | 200, 28 KB Atom | **미등재** | 열리기는 하나 **다른 문서**다. permalink 요청을 서브레딧 피드로 매핑하면 요청한 글이 아닌 것을 성공으로 보고하게 된다 |
| `www.reddit.com` `.json` (www · old) | **403 Blocked** | 미등재 | — |
| `search.naver.com` | 200, 200 KB → 본문 **328 자** = "검색 이용이 제한되었습니다" **차단 안내** | **미등재** | 200 이지만 내용이 차단 고지다. R5 가 robots 로 미등재했던 것이 결과적으로 옳았고, 이유만 달랐다 |
| `html.duckduckgo.com/html` | 202 → anomaly 페이지 | 미등재 | — |
| `lite.duckduckgo.com/lite` | **200**, 실검색결과 2,694 자 | **W5 검색 소스 후보** | Phase 0 어댑터가 아니라 `search_sources:` 대상 |
| `www.bing.com/search` | **200**, 실검색결과 1,949 자 | **W5 검색 소스 후보** | 〃 |
| wikipedia opensearch · arXiv · Crossref · OpenAlex · StackExchange · GitHub search | 전부 200 | **W5 검색 소스 후보** | 키 불요 |

**결론: `api_index.yaml` 은 4/20 그대로. W2 에서 늘어난 항목은 없다.**

계획서는 W2 를 "robots 로 막혔던 어댑터 복원" 으로 잡았지만, 실측은 **복원할 어댑터가
없다**고 답했다 — linkedin 은 어댑터가 필요 없어졌고, reddit·naver 는 robots 와 무관한
이유로 여전히 안 된다. 인덱스에 항목을 채우는 것 자체는 목표가 아니므로 채우지 않는다
(NG-8: 등재가 거짓 '지원' 표기가 된다).

### 파생 결함 2 건 (W2 가 드러낸 것)

1. **거짓 성공 (NG-10) — W6 의 직접 근거.** naver 차단 안내 페이지(328 자)를 open-reach 가
   `ok=True` 로 보고한다. `MIN_ARTICLE_CHARS=200` 을 넘겼고 nav_shell 도 js_shell 도
   아니어서 현행 `detect.classify` 를 통과한다. W6 의 링크 비율 상한·문장부호 밀도 판정이
   겨냥하는 바로 그 형태다.
2. **버전 오보 (수정 완료).** `open_reach.__version__` 이 `1.0.0` 인데
   `.claude-plugin/plugin.json` 은 `1.3.0` 이었다. 이 값은 `HONEST_UA`(Phase 0 에서 우리가
   상대에게 밝히는 신원)와 `bench` 증적의 `engine` 필드를 찍으므로, 지금까지의 모든 Phase 0
   요청이 실제와 다른 버전으로 자기를 소개했고 모든 벤치 증적이 `open-reach@1.0.0` 으로
   잘못 라벨됐다. 값 수정 + `tests/unit/test_version_consistency.py` 로 두 값을 묶어
   재발을 막았다(릴리스마다 한쪽만 올리기 쉬운 형태였다).

---

## §6 W3 — 자기선언 열린문 티어 (완료)

`open_reach/alternates.py`. `fetcher.fetch()` 의 §3(HTTP) 실패 직후, §4 Phase 0 **앞**.

진입 조건은 좁다 — **바이트는 받았는데 본문이 못 쓸 때만**이다. 403·네트워크 실패면
파싱할 HTML 자체가 없으므로 들어가지 않는다. 따라가는 것은 받은 HTML 이 **문자로 적어
둔** 선언뿐이다: JSON-LD `articleBody`(요청 0회로 즉시 본문이라 맨 앞) → RSS/Atom
`rel=alternate` → `amphtml` → JSON oEmbed → 다른 오리진의 `canonical`.

**R2 가 죽인 경로는 부활시키지 않았다.** `m.`·`amp.` 접두를 맹목적으로 붙여 보는 변형은
12건 중 0건이었고(NG-10), 이 티어는 그 자리를 "선언이 없으면 **요청을 만들지 않는다**"로
채운다. 유닛 `test_alternates.py` 가 선언 없는 HTML 에 대해 transport 호출 **0회**를
단언한다 — 동작이 아니라 요청 수로 고정한 이유는, 맹목 변형은 결과가 아니라 회선을
쓰는 것 자체가 위반이기 때문이다.

경계: 후보 URL 마다 `policy.check_url` 재통과(NG-11 — 원본이 공개였다는 사실은 그것이
가리키는 주소의 안전을 보증하지 않는다), 예산 2건, 가져온 대체 표현도 `detect.classify`
를 그대로 통과해야 성공. 특히 **피드를 받았는데 요청한 문서가 그 안에 없으면 실패**로
둔다 — 같은 호스트의 다른 글을 돌려주고 성공이라 부르는 것이 이 티어의 가장 그럴듯한
거짓말이다. `models.ROUTES` 에 `"alternate"` 추가(닫힌 집합).

## §7 W4 — 병렬 배치 (완료)

`open_reach/batch.py` + `fetch --batch <파일|->` · `--concurrency N`(기본 4 · 상한 8).
목록 상한 50, URL 당 NDJSON 1줄(단건 `FetchResult` 스키마 그대로).

**페이싱을 새로 만들지 않은 것이 설계의 핵심이다.** `transport.host_gate` 가 이미
호스트당 동시성 1 + `MIN_HOST_INTERVAL_S=1.0` 을 락으로 강제하므로 배치는 전역 워커 수만
병렬화한다. 같은 호스트로 몰린 URL 은 워커가 몇이든 직렬로 나간다. 배치가 자기 페이싱을
따로 구현했다면 단건 경로와 두 벌이 되어 한쪽만 고쳐지는 날이 온다.

종료코드: 전부 성공 0 / 하나라도 실패 1 / 실패가 경계 사유뿐이면 2.

## §8 W5 — 검색 계층 (완료, 소스 7건 등재)

`open_reach/search.py` + `search "<질의>"` 서브커맨드. `api_index.yaml` 에 **새 섹션
`search_sources:`** 를 두었다 — 기존 `search:`(판정 전용·요청 없음, AC-B-014-1,
us-b-014 동결)를 오염시키지 않기 위한 분리이며, 실제로 us-b-014 는 무변경으로 통과한다.

**재귀 부재를 구조로 만들었다.** `search.py` 는 `fetcher`·`batch`·`extract`·`alternates`
를 임포트하지 않는다. 후보를 만드는 코드가 기사 본문에 접근할 수 없으면 "본문에서 링크를
뽑아 다시 큐에 넣기"는 코드로 **표현될 수 없다**. `test_search.py` 는 이것을 문자열 검색이
아니라 AST 임포트 스캔으로 단언한다(주석·독스트링에 모듈 이름이 나오는 것은 금지 대상이
아니다 — 지금 이 문단이 그렇다) + 동적 임포트(`__import__`/`import_module`) 부재도 함께.

### 등재 실측 (2026-09-03, 정직한 UA)

등재 7건: `ddg`(lite.duckduckgo.com) · `hn` · `stackexchange` · `github` · `wikipedia` ·
`crossref` · `openalex`. 전부 200 + 실제 결과 확인, 키 불요.

**미등재 3건과 그 이유** — robots 가 아니라 전부 다른 이유다:

| 후보 | 실측 | 미등재 사유 |
|------|------|------------|
| `www.bing.com/search` | 200, `b_algo` 10건 실재 | 링크가 `bing.com/ck/a?…&u=a1<base64url>` 로 감싸여 **bing 전용 base64 디코더**가 필요하다. ddg 로 같은 종류(일반 웹 검색)를 이미 얻으므로 전용 변환을 추가하지 않는다 — `link_transform` 은 `percent` 하나로 둔다 |
| `export.arxiv.org` | **429** | 200 미실측. 재시도로 밀어붙이지 않는다 (NG-10) |
| `search.naver.com` | 200 이나 본문 **328자** "검색 이용이 제한되었습니다" | 결과가 없다. §5 와 같은 건이다 |

### ddg 광고 누출 — 선언으로 닫았다

정직한 UA 실측에서 결과가 **11건**으로 나왔다. 유기적 10 + 광고 1 이고, 광고는 유기적
결과와 **같은 래퍼·같은 `class='result-link'`** 로 나온다 — 정규식으로는 갈라지지 않는다.
갈라지는 지점은 래핑을 푼 **목적지**다: 광고는 `duckduckgo.com/y.js?ad_domain=…` 로 검색
엔진 자신을 가리킨다.

닫는 방법으로 두 가지를 기각했다. ① ddg 전용 디코더 — 벤더 이름을 코드에 박는다.
② "결과 호스트 == 소스 호스트면 버린다" 는 일반 규칙 — Wikipedia·GitHub·StackExchange·
OpenAlex 는 **결과가 정당하게 소스 호스트에 산다**. 그래서 채택한 것은 선언
`exclude_hosts:`(스키마 검증 · 상한 8 · 하위 도메인 포함, `.` 접두 접미사 비교라
`notduckduckgo.com` 은 안 걸린다)이고, `source`·`verified_at` 옆에 두어 다른 실측 주장과
같은 절차로 리뷰되게 했다. 이런 규칙은 벤더마다 다르고 시간이 지나면 바뀐다.

수정 후 실측: `found: 11 → 10`, 첫 후보가 `duckduckgo.com/y.js?ad_domain=udemy.com…` 에서
`www.geeksforgeeks.org/…` 로 바뀌었다.

## §9 W6 — 본문 추출 품질 (완료, **계획서와 다르게 구현**)

### (A) 밀도 폴백 — 계획대로

`extract.py` 후보 우선순위에 `_density_markdown` 을 `main/article` **다음**, 문서 전체
**앞**에 넣었다. 컨테이너(`div`/`section`/`article`/`main`)별로 `텍스트 길이 /
(링크 텍스트 길이 + 1)` 를 재고, `MIN_ARTICLE_CHARS` 이상인 것 중 최상을 고른다.
문서 전체보다 `DENSITY_GAIN = 1.5` 배는 깨끗해야 채택하는 **데드밴드**를 두었다 — 이득이
미미한데 서브트리로 좁히면 본문 일부를 조용히 버리는 쪽이 손해다.

실측(geeksforgeeks, `<main>` 없음): whole 11,150자, 앞머리가 "Courses / Tutorials /
Interview Prep / …". dense 8,351자, 앞머리 "# Complete Guide to Clean Architecture",
끝이 기사 결론. 데드밴드 덕에 blog.rust-lang.org·blog.cleancoder.com 은 `dense == ""` 로
**건드려지지 않았다**.

컨테이너 스택은 태그 **이름**이 아니라 `_tag_stack` 과 정렬된 `(pushed, counted)` 프레임
스택으로 pop 한다. `<nav><div>…</div></nav>` 의 안쪽 div 는 버려진 영역이라 누른 적이
없는데 이름만 보고 pop 하면 바깥 컨테이너가 깎여 **모든 블록 경로가 조용히 어긋난다**.
nav 안의 div 는 실제 문서에서 흔하므로 가정하지 않고 테스트로 고정했다.

### (B) 성공 판정 — 계획서 문구에서 이탈

계획서는 "`detect.classify` 성공 판정에 **링크 비율 상한·문장부호 밀도**를 더한다" 였다.
**두 축 다 쓰지 않았다.** 실측이 먼저다 — 이 작업의 유일한 근거 사례(§5 파생결함 1:
search.naver.com)를 포함해 4개 페이지를 실제로 재고 결정했다.

| 페이지 | HTML | 추출 | 문장부호/1k | 링크 | 수확률 |
|--------|------|------|------------|------|--------|
| **search.naver.com** (차단 안내) | 713,695 | **226** | 13.3 | **없음** | **0.03%** |
| blog.rust-lang.org | — | 16,234 | 38.2 | 많음 | 17% |
| blog.cleancoder.com | — | 9,250 | — | — | 25% |
| geeksforgeeks | — | 8,351 | — | — | 3.3% |

- **문장부호 밀도로는 못 가른다** — 차단 안내문은 산문이다. 226자짜리 "AI가 생성한 결과는
  정확하지 않을 수 있습니다" 는 문장부호가 정상 범위다.
- **링크 비율 상한은 쓰면 안 된다** — 안내문에는 링크가 아예 없어서 애초에 안 걸리고,
  더 나쁜 것은 그 축이 `NAV_SHELL_MAX_CHARS` 주석에 **이미 실측으로 기록된 결정**과
  정면 충돌한다는 점이다: 블로그 인덱스·이슈 목록·소스 코드 뷰는 링크 밀도가 높아도
  진짜 본문이라 성공으로 받기로 명시돼 있다. 계획서 문구를 그대로 따랐으면 그 결정을
  근거 없이 뒤집었을 것이다.

실제로 가르는 축은 **수확률**(`len(extracted) / len(html)`)이었고, 분리도가 ~100배다.
`MIN_YIELD_RATIO = 0.005` · `MIN_YIELD_HTML_CHARS = 50_000`, 그리고 `len(extracted) <
NAV_SHELL_MAX_CHARS` 조건을 둬서 **위에서 보호하기로 한 영역(추출량이 큰 페이지)은
구조적으로 건드릴 수 없게** 했다.

R5 검색 면제 **밖**에 배치했다 — AC-B-014-3 의 "면제는 nav_shell 하나" 를 그대로 지킨다.
선언된 검색 URL 이라도 70만 자를 받고 226자를 건졌다면 그것은 "결과 목록을 본문으로
인정" 이 아니라 결과 목록을 **못 받은** 것이다.

`test_extract_density.py` 12종. 회귀 방벽 1종은 "큰 문서 안의 짧은 줄로만 된 긴 본문"
(blog.rust-lang.org 형태)이 그대로 성공인지를 고정한다.

---

## §10 종료 조건 — `rate_http_only` 실측 (2026-09-03)

`rate_http_only` 무회귀가 하드 종료 조건이다(R2 승계 — Phase 0 구제가 HTTP 실력 저하를
가리지 못한다). W6 은 이 라운드에서 **유일하게 기존 성공을 실패로 뒤집을 수 있는** 변경이라
독립 커밋으로 분리한다.

### 1차 측정에서 실제로 회귀가 나왔고, W6 결함이었다

3회 실측 `rate_http_only = 0.917` (11/12), `by_reason: {"validation_failed": 3}`,
엔진 자체 판정 `regression=regressed`. R5 기록은 1.000(12/12)이므로 데드밴드 3%p 를
넘는 회귀다.

원인 추적 — `www.bankofamerica.com`:

| | 문자 수 |
|---|---|
| HTML | 323,772 |
| 문서 전체 추출 | 3,566 |
| **밀도 폴백이 고른 서브트리** | **625** (앱스토어 개인정보 안내) |

밀도 게인 데드밴드는 **비율만** 본다. 링크가 하나도 없는 625자 안내문은 밀도가 압도적이라
데드밴드를 여유롭게 통과했고, 그렇게 본문의 83%를 버린 결과가 이번엔 §9(B)의 수확률
판정에 걸려 `validation_failed` 가 됐다. **W6 의 두 부품이 서로를 물어 멀쩡한 성공을
뒤집은 것**이다.

수정: 분량 하한을 두 겹으로 만들었다 — 절대치 `MIN_ARTICLE_CHARS` 에 더해 문서 본문 대비
비율 `MIN_COVERAGE = 0.5`. 고르는 것은 "가장 깨끗한 조각"이 아니라 "본문이 있는 자리"다
(AC-B-018-1b). 회귀 테스트 `test_density_does_not_trade_the_body_for_a_clean_scrap` 는
조각이 실제로 밀도 1위임을 전제로 고정한 뒤 본문이 살아남는지를 단언한다.

수정 후 `www.bankofamerica.com` 은 다시 `success`(2,435자), `geeksforgeeks` 는 8,351자로
무변화.

### 2차 측정 — W6 회귀 0, 잔여 1건은 라이브 사이트 변화

수정 후 3회 실측 `rate_http_only = 0.917` (11/12)로 수치는 같지만 **사유가 바뀌었다**:
`by_reason: {"waf_challenge": 1}` — `www.leboncoin.fr` 이 403 + 771바이트
"Please enable JS and disable any ad blocker"(DataDome)를 준다.

W6 탓인지 아닌지는 추론하지 않고 **같은 환경에서 W6 만 끄고 다시 쟀다**
(`extract.py`·`detect.py` 를 HEAD 로 되돌려 1회 실행):

| 조건 | rate_http_only | by_reason |
|------|----------------|-----------|
| W6 **ON** (3회) | 0.917 | `waf_challenge: 1` |
| W6 **OFF** (동일 시각대 1회) | **0.917** | `waf_challenge: 1` |

**W6 로 인한 회귀는 0 이다.** R5 의 1.000 과의 차이는 leboncoin.fr 이 그동안 우리의
정직한 UA 를 막기 시작한 것이고, 우리는 프록시 로테이션·신원 위장을 하지 않으므로 그때는
그냥 막힌다 — 계획서 위험 1번이 실제로 관측된 사례다. 지어내지 않고 `waf_challenge` 로
정직하게 실패한다(NG-10).

측정값을 1.000 으로 되돌릴 방법은 배터리에서 그 URL 을 빼는 것뿐인데, 그것은 측정을
고치는 게 아니라 **측정 대상을 고르는** 짓이라 하지 않는다.

holdout(SC-6)은 `bench/holdout.yaml` 이 R3 에서 이미 1회 소진됐다(G-7: 개발 중 실행 이력이
남으면 무효). 새 `bench/r6-holdout.yaml` 을 마지막에 딱 한 번 돌리거나, 정직하게
"미측정" 으로 남긴다.

---

## §11 A0 70건 전수 재측정 — 원본 대비 격차의 R6 시점 귀속 (2026-09-03)

`bench/a0-sample.txt` 70건을 R6 코드로 다시 돌리고(증적 `bench/evidence/r6-a0-part1.ndjson`,
`r6-a0-part2.ndjson`), R1 이 캡처해 둔 원본 결과(`bench/evidence/orig-detail2.json`)와
**URL 단위로** 대조했다. `compare --original-cmd` 를 쓰지 않은 이유는 원본 CLI 가 이 머신에
더 이상 설치돼 있지 않기 때문이다. 따라서 **원본 쪽 숫자는 R1 시점의 기록**이고 우리 쪽은
2026-09-03 실측이다 — 그 사이의 사이트 변화가 양쪽에 다르게 반영된다는 점을 먼저 적어 둔다.

| | 성공 | 비고 |
|---|---:|------|
| 원본 (R1 기록, HTTP 티어만) | 64 / 70 | 성공 판정은 전부 `weak_ok` = "바이트를 받았다" |
| open-reach **R1** | 60 / 70 | |
| open-reach **R6** | **62 / 70** | robots 기본 off · 브라우저 티어 미사용 |

### 격차 4건의 R6 시점 귀속

| URL | R1 당시 사유 | R6 실측 | 귀속 |
|-----|-------------|---------|------|
| `www.linkedin.com/company/…` | `policy_blocked/robots` | **성공, 본문 11,105자** | **닫혔다.** R1 이 "윤리 경계"로 적었던 2건 중 1건 |
| `www.reddit.com/r/programming/` | `policy_blocked/robots` | `waf_challenge` (3회 전부 blocked) | **사유가 바뀌었다.** robots 는 더 이상 이유가 아니고, 이제는 상대가 실제로 막는다. 프록시 로테이션·신원 위장을 하지 않으므로 여기서는 그냥 막힌다(계획서 위험 1번) |
| `crates.io/crates/serde` | 성공 정의 차이 | `validation_failed` | **불변, 의도된 것.** 원본이 성공으로 센 5,056바이트의 본문은 여전히 73자 JS 안내문이다 |
| `netflixtechblog.com/` | 성공 정의 차이(메뉴 껍데기 268자) | `waf_challenge` (redirect×6 → challenge) | **사이트가 변했다.** R1 때는 200 껍데기였고 지금은 챌린지다. 원본의 125,385바이트는 R1 시점 값이라 지금 값이 아니다 |
| `forum.djangoproject.com/` | (R1 격차 아님) | `validation_failed` | **W6 가 뒤집은 유일한 건.** 아래 참조 |

**"실제 돌파력 격차"는 R1 과 같이 여전히 0 건이다.** 새로 열린 것 2건
(`stackoverflow.com` 2건 — 원본은 `exhausted`, 우리는 964자·2,675자 취득)이 있어 순증이다.

### W6 가 A0 에서 뒤집은 1건 — 오탐이 아니라 판정 강화의 의도된 결과

`forum.djangoproject.com/` 은 228,043바이트를 주고 추출은 **792자**다. 내용은
"Announcements / Using Django / Django Internals …" — Discourse **카테고리 목록**이고,
글이 아니다. `_is_starved` 가 이것을 잡는다(수확률 0.0035 < 0.005, html ≥ 50,000자).

이것을 오탐으로 보지 않는 근거는 R1 보고서 자신이다 — R1 은 원본이
`netflixtechblog.com` 의 **메뉴 껍데기 268자**를 성공으로 센 것을 "성공 정의의 차이"라고
적었다. 792자 카테고리 목록은 같은 형태이고 길이만 200자 하한 위에 있었을 뿐이다.

폭발 반경은 상수로 묶여 있다: `_is_starved` 는 **추출이 1,000자 미만일 때만** 붙는다
(`NAV_SHELL_MAX_CHARS`). 1,000자를 넘긴 짧은 줄 위주의 진짜 본문(소스 뷰·이슈 목록·블로그
인덱스)은 이 판정을 아예 만나지 않는다.

---

## §12 검증 실행 결과 (2026-09-03)

| 항목 | 결과 |
|------|------|
| 유닛 | **290 / 290** (R6 이전 184 → +106) |
| 동결 인수 | **18 / 18** (`ACCEPTANCE_RESULT: total=18 passed=18 failed=0`, R5 13종 + R6 5종) |
| 재동결 | `acceptance-freeze --approved-by-user` PASS — 21 파일 + `docs/SPEC.md` 해시, `refreezeHistory` 기록 |
| `rate_http_only` | 0.917 (3회) — W6 ON/OFF 동일, §10 참조 |
| A0 70건 | 62 / 70 (R1 60 → +2), §11 |
| SC-6 holdout | **미측정.** `bench/holdout.yaml` 은 R3 에서 소진됐고(G-7) 새 홀드아웃을 구성하지 않았다. 지어내지 않는다(NG-10) |

### 라이브 스모크 증적

| 무엇 | 증적 | 결과 |
|------|------|------|
| 검색 계층 (7소스 fan-out) | `bench/evidence/r6-live-search-2026-09-03.json` | 7소스 전부 200, 후보 dedupe·인터리브 후 취득 4/4 성공 |
| 병렬 배치 | `bench/evidence/r6-live-batch-2026-09-03.json` | 중복 제거 4→3, 입력 순서 보존, exit 1(1건 실패). `news.ycombinator.com/item?id=1` 은 그 글 자체가 본문이 없어 실패 — 같은 어댑터가 정상 글에서는 성공(1,247자) |
| 자기선언 티어 | `bench/evidence/r6-live-alternate-2026-09-03.json` | 선언이 없는 4건(instagram·quora·tiktok·pinterest)은 **이 티어의 요청 0건** — R2 가 0/12 로 폐기한 맹목 변형이 부활하지 않았다. `medium.com/@anthropic` 은 선언된 피드를 따라갔고 요청한 문서가 없어 `mismatch` 로 정직하게 실패. 페이월 글에서는 티어가 아예 뜨지 않는다(NG-2) |
| R1 격차 재측정 | `bench/evidence/r6-r1gap-recheck-2026-09-03.json` | §11 표 |

> 유닛 수치는 리뷰 반영으로 갱신됐다 — §13 에서 **295 / 295**(신규 5종),
> §14 에서 **296 / 296**(신규 1종).

**라이브 성공 사례를 못 만든 것 하나**: 자기선언 티어가 실제로 **본문을 회수하는** 라이브
케이스는 이 라운드 프로브(11개 호스트)에서 나오지 않았다. 대부분 T1 이 이미 성공하거나,
셸이 아무 선언도 달고 있지 않았다. 성공 경로는 동결 인수(us-b-015)와 유닛
(`test_alternates.py`)이 지키고 있고, 라이브 성공은 **미관측**으로 남긴다.

---

## §13 코드 리뷰 라운드 1 (codex, 2026-09-03) — 4 CRITICAL + 1 MEDIUM, 전부 수정

리뷰가 잡은 4건은 **전부 같은 결함의 다른 얼굴**이었다: 자기선언 열린문 티어(W3)가
경계를 만났을 때 그것을 경계로 취급하지 않는다. 이 티어는 R6 에서 새로 생긴 유일한
"실패 후에 더 두드리는" 경로라 위험이 여기 몰린 것이 당연하다.

| # | 심각도 | 결함 | 수정 |
|---|--------|------|------|
| C1 | CRITICAL | `try_alternates` 가 대체 표현에서 `auth_wall`·`paywall` 을 판정하고도 **note 만 남기고 다음 선언으로 넘어갔다**. 마지막에는 `reason=None` 을 돌려줘 사유 자체가 사라진다 | 경계·terminal 판정이면 그 사유를 들고 **즉시 중단**한다 (`alternates.py`) |
| C2 | CRITICAL | 피드/oembed 자리에 **로그인월 HTML** 이 오면 파싱이 실패해 `mismatch`·`error` 로 기록되고 남은 선언을 계속 두드렸다 — 벽을 다른 문으로 미는 짓 | 파싱 실패 지점에서 `detect_wall` 을 먼저 본다. 벽이면 `wall` 로 기록하고 중단 |
| C3 | CRITICAL | 리디렉트 홉에서 `PolicyBlocked` 로 막힌 시도가 `on_attempt` 없이 반환돼, 결과에는 **endpoint 없는 정책 차단**만 남았다 (NG-10) | `outcome="blocked"` 로 이력에 남긴 뒤 반환 |
| C4 | CRITICAL | `fetcher` §3.5 가 대체 티어의 `policy_blocked` 만 소비하고 **나머지 사유는 버린 채** Phase 0·브라우저로 흘려보냈다 | `alt.reason is not None` 이면 그 사유로 즉시 실패. exit 도 1 이 아니라 2 로 정상화 |
| M5 | MEDIUM | `__version__` 과 `plugin.json` 이 `1.3.0` 인 채로 v2.0.0 릴리스에 들어가려 했다 | 둘 다 `2.0.0`. `test_version_consistency` 가 둘을 묶어 놓아 함께 움직인다 |

C4 의 심각도는 **과대 평가로 판단**했다 — 흘러간 뒤의 Phase 0·브라우저도 각자
fail-closed 가드를 통과하므로 실제 요청이 벽을 뚫지는 않는다. 다만 "경계를 만난 뒤
다른 문을 두드린다"는 시도 자체가 NG-1/NG-2 가 금지하는 것이고, 사유가 세탁되어
exit 2 가 1 이 되는 것은 그대로 결함이다. 근본 수정은 같으므로 그대로 반영했다.

**추가 유닛 5종** (`test_alternates.py` 3 · `test_search.py` 2):

- `test_wall_behind_a_declaration_stops_the_whole_tier` — 진입 판정(`worthy`)은 **원본
  HTML** 만 보므로, 벽이 선언 뒤에 있으면 티어는 정상적으로 뜬다. 픽스처는 벽 다음 선언에
  **성공하는 amp** 를 놓아 두어, C2 변이가 살아 있으면 취득에 성공해 버리게 만들었다.
- `test_paywall_in_declared_content_is_not_laundered` — `exit_code() == 2` 로 사유 세탁을 고정.
- `test_hop_blocked_alternate_is_recorded` — 302 로 사설 대역에 넘기는 픽스처.
  `endpoint` 가 어느 선언이었는지까지 단언한다.
- `test_run_drops_private_band_candidates` — 검색 후보에 `169.254.169.254` 가 섞여도
  목록에 나가지 않고, **제외 사실이 stderr 에 남는다**.
- `test_unresolvable_candidate_is_not_dropped` — 반대 방향 고정. 이름이 안 풀리는 것은
  사설 대역을 가리키는 것과 다르므로 거르지 않는다(일시적 DNS 실패로 결과가 조용히
  깎이는 것을 막는다). 취득 시점에 어차피 fail-closed 로 실패한다.

리뷰가 지적한 검색 후보 SSRF(C4 와 같은 항목으로 보고됨)는 `search._blocked_rule` 로
분리했다 — 절단 **전** 후보에 걸리므로 보통은 `--max-results` 건에서 멈추고, 후보가
계속 걸러지는 최악의 경우에도 `PER_SOURCE_CAP × MAX_SOURCE_FANOUT`(25 × 8 = 200)
이 구조적 상한이다(§14 에서 문구 정정).

**동결 영향 없음**: 수정은 전부 소스와 `tests/unit/` 에만 닿았고 `tests/acceptance/` 는
건드리지 않았다. 재동결 불필요.

---

## §14 코드 리뷰 라운드 2 (codex, 2026-09-03) — 신규 CRITICAL/HIGH 0, MEDIUM 1 수정 후 종결

라운드 1 수정분을 대상으로 한 재리뷰. **신규 CRITICAL/HIGH 없음.** 리뷰가 명시적으로
확인해 준 것: `_failure` 불변식·`final_route` 이상 없음, 검색 필터는 인터리브→dedupe→
필터→절단 순서라 결과 수를 불필요하게 깎지 않음.

| # | 심각도 | 결함 | 수정 |
|---|--------|------|------|
| M1 | MEDIUM | C2 수정이 파싱 실패 자리에서 `detect_wall(payload)` 를 **`extracted=""`** 로 불렀다. 그 인자는 "읽을 본문이 실제로 없을 때만 로그인월로 본다"는 안전장치의 입력인데, 빈 문자열은 장치를 통째로 끈다. 결과: 로그인 문구와 `<input type=password>` 가 **내용으로** 실린 정상 피드가 `auth_wall` 로 뒤집히고, 요청한 글이 없을 뿐인 응답이 exit 2 경계 보고가 되며 뒤에 있는 성공하는 선언까지 중단된다 | 두 호출부를 `_wall_of(payload)` 로 통일 — payload 에서 실제로 읽히는 글자를 한 번 뽑아 `extracted` 로 함께 넘긴다. 벽이면 뽑을 것이 없고, 읽을 것이 있으면 벽이 아니다 |
| L2 | LOW | `search._blocked_rule` 주석의 "조회 수는 `max_results` 로 묶여 있다" 가 부정확 — 후보가 계속 걸러지면 모아 둔 후보를 끝까지 훑는다 | 정상 경로 `max_results`, 구조적 최악 `25 × 8 = 200` 으로 정정. §13 본문도 같이 고쳤다 |

리뷰는 "새 테스트들은 실제 벽 양성 케이스만 검증하며 이 변이를 죽이지 못한다"고 정확히
짚었다. 그래서 **위음성이 아니라 위양성 방향**을 고정하는 테스트를 더했다:

- `test_login_words_in_a_working_feed_are_not_a_wall` — 항목이 둘이라 요청한 글이 없는
  **정상 피드**인데, 첫 항목의 본문이 로그인 방법을 설명하며 password 입력을 예시로 담고
  있다. 다음 선언에는 성공하는 amp 를 놓아 두었다. 기대는 `ok=True` + 피드 자리
  `mismatch`. 수정 전 코드로 되돌리면 이 테스트는 `auth_wall` 로 실패한다(변이 사멸 확인).

여기서 위양성이 위음성보다 비싼 이유: 위음성(벽을 놓침)은 다음 선언이 어차피 같은 벽에
막혀 실패로 끝나지만, 위양성(벽이 아닌 것을 벽이라 부름)은 **취득 가능한 문서를 경계
보고로 만들어** 상위 티어까지 차단한다. NG-10 이 금지하는 "없는 돌파를 지어내기"의
거울상 — 없는 벽을 지어내는 것도 같은 종류의 거짓말이다.

**라운드 종결.** 하드 조건(open CRITICAL/HIGH 0)을 라운드 2 에서 충족했고, M1 은
deferred 로 미루지 않고 그 라운드에 수정했다. 수정은 소스와 `tests/unit/` 에만 닿아
**동결 영향 없음** — 재동결 불필요.

**검증 재실행**: 유닛 **296 / 296**(신규 1종), 동결 인수 **18 / 18** PASS (exit 0).
