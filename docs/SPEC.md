# SPEC — open-reach

> **범위**: 이 문서는 `overview.md`(정의 문서)가 정한 경계 안에서 **무엇을 어떻게 만드는가**를 정의한다.
> 여기에 없는 동작을 구현에서 임의로 추가하지 않는다 (스펙 공백 시 임의 구현 금지).
> **Round 1 범위만** 구현 계약으로 확정한다. R2~R4 기능은 아래 "Round 경계"에 위임 조건을 명시한다.

**projectScope**: `{hasFrontend: false, hasBackend: false}` — library/CLI 플러그인.
HTTP 서버·UI 레이어가 없으므로 외부 계약은 **CLI 서브커맨드 + Python 함수 시그니처**다.

---

## Target Users (Personas Reference)

- **P1. 마켓플레이스 운영 개발자** — devncat 플러그인을 직접 만들고 유지보수한다. 리서치 중 fetch 실패로 작업이 끊기는 것이 핵심 고통이며, 돌파율을 수치로 보고 회귀를 감지할 수 있어야 한다.
- **P2. devncat 플러그인 사용자** — Claude Code에서 open-reach 스킬을 통해 간접 사용한다. 설치 개입 0회와 "실패했으면 왜 실패했는지"만 요구한다.

## Core Jobs (JTBD Reference)

- **J1**: 차단된 공개 URL을 만났을 때, 본문을 마크다운으로 얻어 리서치를 계속하고 싶다.
- **J2**: 접근이 실패했을 때, 분류된 사유와 시도 경로를 받아 다음 행동을 판단하고 싶다.
- **J3**: 엔진을 고쳤을 때, 돌파율이 올랐는지 내렸는지 수치로 확인하고 싶다.
- **J4**: 로그인월·페이월이면 우회 시도 없이 즉시 그 사실을 통보받고 싶다.
- **J5**: 같은 호스트를 다시 조회할 때, 지난번 성공 경로를 먼저 시도해 시도 횟수를 줄이고 싶다.

---

## Context & Existing System

<!-- provenance: repo-fact:overview.md -->

- **그린필드 코드베이스** — 신규 저장소 `vp-k/open-reach`. 기존 소스 코드 자산이 없다.
- **배포 컨텍스트는 브라운필드**다. devncat 마켓플레이스의 기존 6개 플러그인과 동일한 규약을 따라야 한다:
  - 플러그인 루트에 `.claude-plugin/plugin.json` (name, version, description)
  - 슬래시 커맨드는 `commands/*.md`, 스킬은 `skills/<name>/SKILL.md`
  - 마켓플레이스 등록 형식은 HTTPS git URL 직접 참조
  - 버전 변경 없이 동작 변경을 배포하지 않는다 (SemVer)
- **런타임 전제** (설치 환경에서 실측 확인된 사실):
  - Python 3.13.3 / pip 25.3
  - `curl_cffi` 0.16.1 은 `cp310-abi3-win_amd64` 사전빌드 휠이 존재해 컴파일러 없이 설치된다
  - `lxml` 6.0.2, `beautifulsoup4` 4.15.0, `yt-dlp` 2026.3.17, `pytest` 9.0.2 는 이미 설치되어 있다
  - Playwright / patchright 는 **미설치**다 — 브라우저 티어는 지연 설치 대상이다
- **깨지면 안 되는 것**: 이 저장소는 다른 플러그인과 코드를 공유하지 않는다. 파괴 위험이 있는 기존 API는 없다.

---

## Success Criteria

<!-- provenance: user-fact -->

**North Star Metric — 배터리 돌파율** = 정답 대조(`expected`)를 통과한 URL 수 ÷ 배터리 총 URL 수.
단일 수치만 인용하는 보고는 금지하며, 항상 `by_vendor` / `by_route` / `by_reason` 분해와 함께 출력한다.

| ID | 기준 | 측정 방법 | 합격선 | 검증 Round |
|----|------|-----------|--------|-----------|
| SC-1 | 초기 역량 검증 (원본 대조) | 동일 배터리를 원본 insane-search와 open-reach에 각각 실행. 원본 commit SHA·실행 일시·OS·네트워크 식별자를 증적으로 동결 | `open-reach >= insane-search x 0.9` (**R1 한정 게이트**) | R1 |
| SC-2 | 절대 하한 | Tier-1 배터리 돌파율, 3회 실행 중앙값 | `>= 80%` AND 벤더별 `>= 50%` | R3 |
| SC-3 | 경계 판정 정확도 | 라벨링된 wall/challenge 음성셋 + 공개 본문 양성셋 | wall/paywall을 success로 판정 **0건**(hard fail), 재현율 `>= 0.95` | R1 |
| SC-4 | 실패 사유 분류 | 실패 건의 사유 분포 | 분류율 `100%` AND `unknown` 비율 `<= 10%` | R1 |
| SC-5 | 지문표 자동 갱신 | `refresh` 1회 실행의 diff | 수동 편집 `0회` AND 경계 위반 학습 `0건` | R3 |
| SC-6 | 신규 도메인 일반화 | holdout 배터리 돌파율 | Tier-1 대비 낙폭 `<= 15%p` | R3 |
| SC-7 | 깨끗한 환경 설치 | 새 환경에서 설치 → 첫 `fetch` 성공까지 사람 개입 횟수 | `0회` (T1 경로 기준) | R3 |
| SC-8 | 벤더 감지 정확도 | 배터리 각 항목의 `expected.waf_vendor`와 실행 시 감지값 대조 | 오탐(다른 벤더로 단정) **0건**(hard fail) AND 미탐(`unknown_challenge`로 흘림) `<= 10%` | R2 |
| SC-9 | API 라우팅 무결성 | Phase 0 경로로 성공한 건 전수 감사 | **설정된 robots 모드 위반 0건**(R6 개정 — `off`에서 robots 요청 **0건**, `enforce`에서 미검사 **0건**), 임퍼소네이션 사용 **0건**, 인덱스에 없는 요청 **0건**, `value_pattern` 미검증 치환 **0건** — 각각 hard fail | R2 / R6 |

**측정 규약** — 3회 실행 중앙값으로만 판정한다. `battery_hash`가 달라진 실행은 회귀 비교 대상에서 제외한다. holdout 배터리는 개발 중 실행 이력이 남으면 무효 처리한다. 회귀 판정에는 **dead-band 3%p**를 적용해 네트워크 지터로 인한 거짓 회귀를 차단한다.

**SC-1의 소멸 대비** — 원본이 유료화되거나 실행 불가로 판명되면 SC-1은 `unmeasurable`로 마킹되고 이후 릴리즈 판정에서 제외된다. 지속 기준은 SC-2 + SC-6가 담당한다.

---

## User Stories — Frontend

<!-- provenance: user-fact -->

N/A — 프론트엔드 없음 (`projectScope.hasFrontend=false`). UI 레이어도 화면도 존재하지 않는다.

---

## User Stories — Backend

<!-- provenance: user-fact -->

> **ID 규약**: 이 프로젝트에는 HTTP 서버가 없다. auto-complete-loop 게이트가 `US-F-*`/`US-B-*` 형식만 인식하므로
> **엔진·CLI 동작을 `US-B-*`로 표기**한다. "B"는 백엔드 서버가 아니라 **비-UI 실행 주체**를 뜻한다.
>
> 각 User Story의 **Acceptance Criteria(인수 기준)** 는 아래 `AC-B-*`이며, `tests/acceptance/` 의 동결 인수 테스트와 1:1 대응한다.

### US-B-001 — 공개 본문 조회
As a 리서처, I want to 차단된 URL을 넘기면 공개 본문을 마크다운으로 받고, so that 리서치를 끊김 없이 계속할 수 있다. (J1)

- **AC-B-001-1**: 공개 HTML 문서 URL로 `fetch`하면 exit code `0`, stdout에 `FetchResult` JSON이 출력되고 `ok=true`, `content_markdown` 길이 `>= 200`자다.
- **AC-B-001-2**: 반환된 `content_markdown`에는 `<script>`·`<style>`·네비게이션·푸터 텍스트가 포함되지 않는다 (본문 추출).
- **AC-B-001-3**: `metadata`에 `title`, `final_url`, `content_type`, `fetched_at`(ISO-8601 UTC)이 채워진다.
- **AC-B-001-4**: 본문은 **디스크에 기록되지 않는다** — `fetch` 실행 후 관측 로그 파일에 `content_markdown` 문자열이 등장하지 않는다 (NG-12).

### US-B-002 — 분류된 실패 보고
As a 리서처, I want to 실패 시 분류된 사유와 시도 경로 목록을 받고, so that 다음 행동을 판단할 수 있다. (J2)

- **AC-B-002-1**: 실패한 `fetch`는 0이 아닌 종료 코드를 반환하고, `ok=false`, `failure_reason`이 **11종 분류 중 정확히 하나**다 (분류 불능은 `unknown`이며 그것도 정식 분류다).
- **AC-B-002-2**: `attempts` 배열에 시도한 모든 경로가 순서대로 기록되고, 각 원소는 `route`·`impersonate`·`url_variant`·`status`·`elapsed_ms`·`outcome`을 갖는다.
- **AC-B-002-3**: 404 응답은 `not_found`, 5xx는 `server_error`, DNS/TLS/타임아웃은 `network`로 분류된다.
- **AC-B-002-4**: `attempts`가 빈 배열인 실패 결과는 존재할 수 없다 — 정책 차단(`policy_blocked`)도 차단 판정을 `attempts[0]`에 `route=policy`로 남긴다.

### US-B-003 — 경계 도달 시 즉시 중단
As a 리서처, I want to 로그인/페이월이면 우회 시도 없이 즉시 통보받고, so that 도구가 넘지 말아야 할 선을 넘지 않았음을 신뢰할 수 있다. (J4)

- **AC-B-003-1**: 로그인월 응답을 받으면 `failure_reason="auth_wall"`이고, 판정 시점 이후 `attempts`에 **새 원소가 추가되지 않는다** (상위 티어 진입 함수 호출 자체가 거부됨).
- **AC-B-003-2**: 페이월 응답(본문 중략 마커 또는 `isAccessibleForFree=false` 메타)을 받으면 `failure_reason="paywall"`이며 마찬가지로 추가 시도가 없다.
- **AC-B-003-3**: `auth_wall`/`paywall`/`policy_blocked` 판정 시 종료 코드는 `2`다 (일반 실패 `1`과 구분되어 호출자가 "경계 도달"을 프로그래밍 방식으로 식별할 수 있다).
- **AC-B-003-4**: 사설 IP·루프백·링크로컬·CGNAT 대역 또는 `http`/`https` 외 스킴 URL은 네트워크 요청 없이 `policy_blocked`로 거부된다 (NG-11). 유일한 예외는 Constraints 보안 절의 **테스트 픽스처 오리진**이며, 오리진이 완전히 일치할 때만 적용된다.
- **AC-B-003-5**: 리디렉션은 **매 홉마다** 재검사한다. 공개 주소에서 사설 대역으로 리디렉션되면 그 홉에서 `policy_blocked`로 중단된다.
- **AC-B-003-6** (R6 개정, 사용자 승인 재동결): robots.txt 는 **경계가 아니라 모드**다. 기본값 `off` 에서는 robots.txt 를 **조회하지 않으며**(요청 0건) `Disallow` 경로도 취득한다. `--respect-robots`(= `--robots enforce`)를 주면 R5 까지의 동작이 **정확히 복원**되어 `policy_blocked`·종료 코드 2·`attempts[0].route="policy"`·`rule="robots"` 가 그대로 나온다. `--robots advisory` 는 조회하되 차단하지 않고 오리진당 1회 stderr 로 보고한다. 모르는 모드는 조용히 `off` 로 떨어지지 않고 거부된다 — robots 를 켠 줄 알고 끈 채로 도는 것이 가장 나쁜 실패다 (NG-10). **SSRF 는 세 모드 어디에서도 빠지지 않는다** (AC-B-003-4·-5 불변, NG-11 은 개정 대상이 아니다).

### US-B-004 — 돌파율 산출
As a 개발자, I want to 배터리를 1회 실행해 현재 돌파율 수치를 얻고, so that 개선·회귀를 사람 판단 없이 판정할 수 있다. (J3)

- **AC-B-004-1**: `bench --tier 1`은 마지막 줄에 `BENCH_RESULT: rate=<0.000~1.000> total=<N> passed=<N> failed=<N>` 을 출력하고, 그 앞에 `by_vendor`·`by_route`·`by_reason` 분해를 **반드시** 출력한다. 분해 없는 출력 경로는 존재하지 않는다.
- **AC-B-004-2**: 배터리 거버넌스 위반 시 측정 전에 exit code `3`으로 중단한다 — 배터리가 선언한 `vendor_scope` 범위의 벤더 중 하나라도 2개 미만(G-1, `role: production` 한정. `vendor_scope` 미선언 시 범위는 벤더 9종 전체), Tier-1에 음성 케이스가 0건(G-3), `expected`/`tier`/`waf_expected`/`added_reason` 중 하나라도 누락된 항목 존재(G-4), Tier-1 항목 수 50 초과(G-6).
- **AC-B-004-3**: 음성 케이스(로그인월·페이월·챌린지) 중 하나라도 `success`로 분류되면 돌파율과 무관하게 **벤치 전체가 fail**(exit `3`)이다.
- **AC-B-004-4**: 각 실행은 `BenchRun` 1건을 `bench/history.jsonl`에 append하며, 기존 줄을 수정·삭제하지 않는다.
- **AC-B-004-5**: URL 간 상태가 격리된다 — 배터리를 **셔플 실행한 결과가 순서 실행 결과와 dead-band(3%p) 안에서 일치**한다.

### US-B-005 — 원본 대조
As a 개발자, I want to 원본과 동일 배터리를 돌려 두 돌파율을 나란히 비교하고, so that 원본이 사라지기 전에 우리 위치를 증적으로 남길 수 있다. (J3)

- **AC-B-005-1**: `compare`는 두 엔진의 돌파율과 함께 **실행 조건 증적**(원본 commit SHA, 실행 일시 UTC, OS·아키텍처, Python 버전, 배터리 해시)을 하나의 JSON으로 출력한다.
- **AC-B-005-2**: 원본을 실행할 수 없으면(미설치·유료화·오류) `status="unmeasurable"`과 사유를 출력하고 exit code `0`으로 종료한다 — 측정 불가는 실패가 아니라 **기록해야 할 사실**이다.
- **AC-B-005-3**: 증적 JSON은 `bench/compare-<UTC타임스탬프>.json`으로 저장되며, 같은 파일명이 이미 있으면 덮어쓰지 않고 exit code `4`로 중단한다.

### US-B-006 — 성공 경로 재사용
As an 엔진, I want to 성공한 (호스트, WAF 벤더, 경로, 지문)을 기록해 다음 조회에서 먼저 시도하고, so that 반복 조회의 시도 횟수를 줄일 수 있다. (J5)

- **AC-B-006-1**: 성공한 시도는 `Observation` 1건을 `observations.jsonl`에 append한다.
- **AC-B-006-2**: 기록되는 URL은 **정규화**된다 — 스킴+host+path만 남기고 query·fragment·userinfo를 제거한다.
- **AC-B-006-3**: 관측 로그에는 `Set-Cookie`·`Authorization`·`Cookie` 헤더 값, 요청 본문, 응답 본문이 **어떤 필드로도** 기록되지 않는다. 스키마는 허용 필드 화이트리스트로 강제되며, 화이트리스트 밖 키는 기록 시점에 거부된다 (NG-4).
- **AC-B-006-4**: 동일 호스트 재조회 시 직전 성공 경로가 `attempts[0]`에 온다.
- **AC-B-006-5**: `auth_wall`·`paywall`·`policy_blocked`로 끝난 시도는 관측으로 학습되지 않는다 — 경계 위반 경로를 우선순위로 올리는 일이 없다 (SC-5).

### US-B-007 — 지문표 자동 갱신
As a 개발자, I want to 재측정 1회로 TLS 후보 리스트가 갱신되게 하고, so that 시드가 노화되어도 손으로 표를 고치지 않는다. (J3)

- **AC-B-007-1**: `refresh`는 관측 로그를 근거로 `profiles.yaml`의 `impersonate_candidates` 순서를 갱신하고 **diff를 stdout에 출력**한다.
- **AC-B-007-2**: 갱신된 각 벤더 프로파일의 `last_reviewed`가 실행 일자로 갱신된다.
- **AC-B-007-3**: `refresh`는 **원자적으로** 기록한다 — 같은 디렉토리의 임시 파일에 쓴 뒤 rename하며, 중단되어도 `profiles.yaml`이 부분 기록 상태로 남지 않는다.
- **AC-B-007-4**: 관측이 0건이면 파일을 수정하지 않고 `no observations` 를 출력하며 exit code `0`으로 종료한다.

### US-B-008 — 응답 진위 판별
As a 리서처, I want to 응답이 챌린지 페이지인지 실제 본문인지 자동 판별되길 원한다, so that "무언가 받았다"가 성공으로 오계상되지 않는다. (J1, J4)

- **AC-B-008-1**: HTTP 200이지만 본문이 WAF 챌린지·동의 배너·검색 결과·오류 페이지면 `ok=false`이며 `failure_reason`은 `waf_challenge` 또는 `validation_failed`다. **예외(R5, US-B-014)**: 사용자가 **명시적으로 검색 결과 URL을 준 경우**(입력 URL 자체가 플랫폼 검색 엔드포인트)에는 결과 목록을 유효 본문으로 인정한다 — 이때는 검색 결과가 "받으려던 것"이기 때문이다. 임의 URL에서 **우발적으로** 나온 검색 페이지는 여전히 `validation_failed`다. 판별은 입력 URL의 명시성으로 하며, 응답을 보고 사후에 검색이라 우기지 않는다.
- **AC-B-008-2**: 판별기는 **상태 코드 단독으로 판정하지 않는다** — 403/418/503 + 제목 패턴 + 본문 길이(`< 500`자)와 차단 어휘의 조합으로 판정한다.
- **AC-B-008-3**: CAPTCHA 위젯이 감지되면 **해결을 시도하지 않고** 즉시 `waf_challenge`로 중단한다 (NG-3). 판정 시점 이후 추가 시도가 없어야 하며, 출력에 CAPTCHA 해결 관련 필드가 존재하지 않는다.
- **AC-B-008-4**: `bench` 모드에서는 `expected`(제목 포함 문자열 / 본문 포함 문자열 / 최소 길이 / 정규화 해시 중 정의된 조합) 대조를 추가로 통과해야 `passed`로 계상된다. 대조 실패는 `validation_failed`다.

### US-B-009 — 벤더별 측정 가능성 확보 (R2)

<!-- provenance: repo-fact -->

As a 유지보수자, I want to 지문표가 선언한 벤더마다 실측 표본이 배터리에 있길 원한다, so that SC-2의 "벤더별 `>= 50%`"가 미측정이 아니라 판정 가능해진다. (J4)

> 지문표(`engine/profiles.yaml`)에는 이미 9종이 선언돼 있다. 없는 것은 감지기가 아니라 **표본**이며, R1 후보 87건 실측에서 벤더별 2건 이상을 채운 것은 4종(cloudflare·akamai·fastly·imperva)뿐이다. 미확보 5종은 datadome·perimeterx·aws_waf·kasada·f5다.

- **AC-B-009-1**: R2 종료 시 출하 배터리의 `vendor_scope`는 **감지기가 신뢰도 `1.0`으로 지목한 URL이 2건 이상 확보된 벤더 전체**를 포함한다. 확보된 벤더를 `vendor_scope`에서 제외하는 것은 G-8 위반이다.
- **AC-B-009-2**: 표본 확보 시도는 **후보 목록 1회 실측**으로 한정한다. 후보는 벤더 공개 문서와 MIT 시드(ADR-003) 범위에서만 수집하며, 사이트를 무작위로 훑지 않는다 (NG-5).
- **AC-B-009-3**: 2건을 채우지 못한 벤더는 `vendor_scope`에 넣지 않고, `vendor_scope_reason`에 **벤더명과 실측 건수**를 남긴다. SC-2는 그 범위에서 판정한다 (NG-8, NG-10).
- **AC-B-009-4**: `bench` 출력은 배터리 각 항목의 `expected.waf_vendor`와 실행 시 감지값을 대조해 **오탐·미탐 건수**를 낸다. 이 값이 SC-8의 입력이다.

### US-B-010 — Phase 0 공개 API 라우팅 (R2)

<!-- provenance: repo-fact -->

As a 리서처, I want to 원문 HTML로 본문을 얻지 못한 사이트가 스스로 공개한 API가 있으면 그 길로 본문을 얻길 원한다, so that 차단을 뚫는 대신 **열려 있는 문으로 들어간다**. (J1)

> **발견은 규칙화되지 않는다** — crates.io·pypi.org·github.com·news.ycombinator.com 실측에서 `<link rel="alternate" type="application/json">` 0건, HTTP `Link:` 헤더 0건, JSON-LD 0건이다(`bench/evidence/r2-discovery-probe.json`). 따라서 **사이트별 인덱스 파일**이 유일한 실행 경로이며, `/api/v1/…` 같은 경로를 추측해 두드리는 것은 스캐닝이므로 하지 않는다.

**경로 선택과 경계**

- **AC-B-010-1**: Phase 0 경로는 **HTTP 경로가 본문 획득에 실패한 뒤에만** 시도한다. 원문이 정상인 사이트에 API 부하를 주지 않으며, 돌파율의 비교 가능성도 이 순서가 지킨다.
- **AC-B-010-2**: 인덱스에 항목이 없으면 시도하지 않는다. URL을 조립하거나 추측하지 않는다.
- **AC-B-010-3**: API URL은 원문과 **별도로 판정**한다. 호스트가 다를 수 있다. 적용되는 robots 모드는 원문 요청과 같다 (AC-B-003-6).
- **AC-B-010-4**: Phase 0 경로에서는 **임퍼소네이션을 사용하지 않는다.** `open-reach/<version> (+<repo-url>)` 형식의 정직한 UA를 보낸다. 기계용으로 열어 둔 문을 브라우저인 척하며 두드리지 않는다 (NG-13).
- **AC-B-010-5**: API가 인증·키를 요구하면(401, 또는 키 안내를 동반한 403) 즉시 중단하고 `auth_wall`로 분류한다. 키를 발급받거나 저장하지 않는다 (NG-1, NG-4).
- **AC-B-010-6**: 쿼터 소진은 `rate_limited`로 실패한다. 쿼터를 늘리려 키를 만들거나 IP를 바꾸지 않는다 (NG-6).
- **AC-B-010-7**: 성공 시 `attempts[]`에 `route="phase0"`인 시도가 남고, 사용한 엔드포인트가 결과에 표기된다. 소비자가 HTML 본문과 구분할 수 있어야 한다.

**2-hop 조립 규칙** — 한 단계로 본문에 닿지 못하는 API가 있다(실측: `crates.io/api/v1/crates/{crate}`의 `crate.max_stable_version`을 다음 경로에 넣어야 README 본문에 닿고, 버전 생략형은 `400`이다). 이를 허용하되, **상대 서버의 응답이 우리 다음 요청 URL에 영향을 주는 첫 경로**이므로 — 리디렉션이 아니라 우리가 자발적으로 조립하는 URL이라 `hop_guard`가 보지 않는 자리다 — 조립 규칙을 계약으로 고정한다.

- **AC-B-010-8**: `chain` 길이는 **최대 2**다. 3단 이상은 로드 실패(종료 코드 3)다.
- **AC-B-010-9**: 한 단계가 다음 단계로 넘기는 값은 **스칼라 1개**뿐이다. `select`가 가리킨 자리에 객체·배열이 있으면 요청하지 않고 중단한다.
- **AC-B-010-10**: 앵커된 `value_pattern`은 **필수**다. 없는 항목은 로드 실패(종료 코드 3)이며, 뽑은 값이 매치하지 않으면 요청하지 않고 중단한다.
- **AC-B-010-11**: 넘겨받은 값은 **경로 세그먼트 1개**로만 치환된다. `/`·`\`·`%`·`:`·`?`·`#`가 포함되면 거부하고, 값 자체가 `.` 또는 `..`이면 거부한다 (`value_pattern`이 이미 막더라도 이중으로 검사한다). 점은 **문자로는 금지하지 않는다** — `1.0.219` 같은 버전 문자열이 정상 세그먼트이기 때문이며, 경로 탈출은 `.`·`..` 세그먼트와 `/`·`\`·`%` 로 막는다. **예외(R5 개정, 사용자 승인 재동결)**: `chain` 이 없는 `endpoints` 항목의 템플릿에서는 치환자를 **쿼리 값 위치**에도 둘 수 있다. 이 항목의 치환 입력은 입력 URL의 캡처 그룹뿐이고 응답에서 온 값이 존재하지 않으므로, 이 금지의 근거였던 "응답이 쿼리 구조를 바꾼다"는 흐름이 성립하지 않는다 (실측: Bluesky XRPC 는 쿼리 파라미터 전용이라 이 예외 없이는 표현 불가). `chain` 템플릿(어느 단계든)의 쿼리 치환자는 여전히 로드 실패(종료 코드 3)다. 쿼리 위치로 치환되는 값도 위 금지 문자에 `&`·`=` 를 더해 거부한다 — 값이 쿼리 구조 자체를 바꿀 수 없다.
- **AC-B-010-12**: **스킴과 호스트는 응답에서 오지 않는다.** 인덱스 템플릿에 적힌 값으로 고정이며, 응답이 우리를 다른 호스트로 보낼 수 없다 (NG-11).
- **AC-B-010-13**: 조립된 URL도 SSRF 가드를 **새로 통과**해야 하며, robots 는 **설정된 모드로 새로 판정**한다. 첫 요청이 통과했다는 사실은 두 번째 요청의 근거가 아니다. R6 개정: `off` 에서는 인덱스 경로에서도 robots 요청이 **새지 않는다**(조립 URL 마다 조회하는 자리였으므로 모드를 따르지 않으면 여기서만 샌다), `enforce` 에서는 조립 URL 의 `Disallow` 가 `policy_blocked` 로 그대로 차단된다.
- **AC-B-010-14**: 한 항목이 쓰는 총 요청 예산은 **3회**(엔드포인트 + 체인 포함)다.

**인덱스 규율과 측정 무결성**

- **AC-B-010-15**: 인덱스는 **최대 20 항목**이며, `source`(해당 API의 공식 문서 URL)와 `verified_at` 누락은 로드 실패(종료 코드 3)다. NG-9가 지문표에서 막은 "사이트 목록의 무한 증식"을 인덱스에서는 상한과 출처 의무로 막는다.
- **AC-B-010-16**: `bench` 출력은 `rate`와 함께 **`rate_http_only`**를 낸다. Phase 0을 켠 뒤에도 R1의 돌파율과 **같은 정의의 값**이 사라지지 않는다.
- **AC-B-010-17**: `bench` 분해에 `rescued_by_phase0` 건수를 낸다. 돌파율 상승이 전송 개선인지 API 구제인지 출력만 보고 갈릴 수 있어야 한다.
- **AC-B-010-18**: 응답이 콘텐츠 라이선스를 명시하면(실측: StackExchange API `content_license: "CC BY-SA 4.0"`) 결과 `metadata`에 함께 싣는다. 본문은 여전히 보관하지 않는다 (NG-12).

### US-B-012 — Phase 0 공개 플랫폼 어댑터 확장 (R5)

<!-- provenance: user-fact -->

As a 리서처, I want to 네이버·레딧·HN·Bluesky처럼 스스로 공개 엔드포인트를 가진 플랫폼은 그 문으로 본문을 얻길 원한다, so that insane-search가 도달하는 플랫폼에 open-reach도 **공개 범위 안에서** 도달한다. (J1)

> 이는 US-B-010의 `api_index.yaml` 메커니즘(2-hop·예산·SSRF·robots 재검사 포함)을 **재사용**하는 확장이다. 새 라우팅 경로를 만들지 않고, 인덱스 항목만 공개 확인 후 추가한다. 근거·후보·경계는 `docs/r5-contract.md`.

- **AC-B-012-1**: R5에서 추가하는 어댑터는 **모두 기존 Phase 0 경로**(AC-B-010-1~18)를 따른다. 별도 코드 경로를 만들지 않으며, 인덱스 항목 추가와 그 항목이 요구하는 최소 변환(2-hop 이내)만 구현한다.
- **AC-B-012-2**: 각 어댑터 항목은 **정직한 UA로 200이 확인된 엔드포인트만** 등재한다(AC-B-010-4 승계). 정직한 UA로 열리지 않는 플랫폼은 Phase 0에 넣지 않는다 — 임퍼소네이션으로 두드려 여는 것은 Phase 0의 정의가 아니며, 없는 돌파를 지어내지 않는다 (NG-10, NG-13).
- **AC-B-012-3**: 어댑터가 로그인·인증을 요구하는 콘텐츠에 닿으면(예: 비공개 Threads/X 게시물) `auth_wall`로 중단한다(종료 코드 2, NG-1). **공개 게시물만** 어댑트하며, 원본이 로그인 게이트 뒤 콘텐츠를 다루는 부분과는 **의도적으로 분기**한다 (r5-contract §4-③).
- **AC-B-012-4**: 추가 항목도 20항목 상한과 `source`·`verified_at` 의무(AC-B-010-15)를 진다. 공개성이 확인되지 않은 플랫폼을 "지원"으로 표기하지 않는다 (NG-8).
- **AC-B-012-5**: `bench` 분해의 `rescued_by_phase0`(AC-B-010-17)는 R5 어댑터 구제분을 포함해 계상한다. 돌파율 상승이 어느 어댑터에서 왔는지 출력으로 갈릴 수 있어야 한다.
- **AC-B-012-6** (R6 개정, 사용자 승인 재동결): 등재 조건은 **정직한 UA 로 200 실측 + `source` + `verified_at`** 이다. robots.txt 는 등재 조건이 아니다 — 기본 모드가 `off` 라 런타임이 차단하지 않으므로, robots 를 이유로 미등재하면 오히려 "지원하지 않는다"는 거짓 표기가 된다. 다만 **200 이 실측되지 않은 호스트는 여전히 등재하지 않는다**(NG-8 의 실체는 robots 가 아니라 "실측 없이 지원이라 적지 않는다"이다). 아래 R5 실측 기록은 개정 전 기준의 판단이며, R6 W2 에서 정직한 UA 200 재실측으로 갱신한다.
  <details><summary>R5 시점 기록 (개정 전 기준)</summary>

  **실측 확정(2026-09-02, `bench/evidence/r5-adapter-probe-2026-09-02.json`)**: `search.naver.com`·`www.reddit.com` 은 `*` 전면 Disallow → 미등재. Threads 는 공개 게시물 데이터가 초기 HTML 에 없는 로그아웃 셸이라 URL 템플릿으로 표현 불가 → 미등재. Mastodon 은 인스턴스 호스트 가변이라 `host` 정확 일치 인덱스로 표현 불가 → 미등재. R5 등재는 **`news.ycombinator.com`(HN Algolia items)·`bsky.app`(getPostThread)** 2건이다.
  </details>

### US-B-013 — Jina Reader 폴백 (R5 — **철회**)

<!-- provenance: user-fact -->

As a 리서처, I want to 다른 모든 경로가 막혔을 때 공개 리더 게이트웨이로 본문 마크다운을 얻는 것을 **내가 명시적으로 켤 때만** 시도하길 원한다, so that 제3자 경유라는 성질을 알고 선택할 수 있다. (J1)

> **철회 (2026-09-02 실측, `bench/evidence/r5-adapter-probe-2026-09-02.json`)**: `r.jina.ai/robots.txt` 는 특정 AI 에이전트 UA 목록만 허용하고 `User-agent: *` 를 전면 `Disallow: /` 한다. open-reach 의 정직한 UA 는 `*` 그룹에 속하므로 리더 요청 자체가 robots 존중(정책 계층, fail-closed)과 충돌한다. 허용 목록의 UA 로 신원을 바꾸어 통과하는 것은 신원 위장이라 하지 않는다(정직한 UA 원칙, NG-13 정신). 따라서 이 US 는 **구현하지 않는다** — robots 가 차단하는 기능을 배선해 두는 것은 없는 돌파를 지어내는 것이다 (NG-10). 원래 AC(AC-B-013-1~6)는 철회와 함께 효력을 잃고, `--allow-reader` 플래그는 도입하지 않는다.

> **R6 정정 — 철회는 유지하되 근거가 바뀌었다.** R6 이 robots 기본값을 `off` 로 뒤집었으므로 위 철회 근거 중 **"robots 존중(fail-closed)과 충돌한다"는 더 이상 성립하지 않는다**. 그 문장을 남겨 두면 문서가 거짓말이 된다. R6 이후 철회를 지탱하는 근거는 둘뿐이다: ① 허용 목록의 UA 로 신원을 바꾸어 통과하는 것은 여전히 신원 위장이다 (NG-13 — 이쪽은 robots 와 무관하므로 개정되지 않았다), ② 제3자 게이트웨이 경유는 R6 이 선택한 레버 3종에 없다. `*` 를 Disallow 한 서버가 실제로 **정직한 UA 요청을 200 으로 응답하는지는 미실측**이며, 실측 없이 재개하지 않는다 (NG-10). **재검토 조건**: 정직한 UA 200 이 실측되고 제3자 경유를 사용자가 명시 승인하면 재개한다 (`docs/operations.md` 의 정기 점검 절차).

### US-B-014 — 명시적 검색 URL 본문 인정 (R5)

<!-- provenance: user-fact -->

As a 리서처, I want to 내가 검색 결과 URL을 직접 줬을 때는 그 결과 목록을 본문으로 받길 원한다, so that 검색 결과 목록이 "검색 페이지라서 실패"(nav_shell)로 오분류되지 않는다. (J1, J4)

> 원래 동기였던 네이버 통합검색은 R5 실측 시점 기준 robots 전면 Disallow 라 접근 자체가 정책 차단이었다 — 검증기 완화로 해결될 문제가 아니었다. 이 US 는 **선언 메커니즘**(`search:` 섹션, Data Model SearchDeclaration)으로 유지한다: 선언된 검색 엔드포인트의 URL 이면 그 결과 목록을 본문으로 인정한다. **R6 정정**: robots 기본값이 `off` 로 뒤집혔으므로 "robots 가 허용하는" 이라는 등재 전제는 더 이상 적용되지 않는다 (AC-B-014-4).

- **AC-B-014-1**: 입력 URL이 **플랫폼 검색 엔드포인트**(인덱스 `search:` 섹션에 선언된 host+`url_pattern`)에 매치하면, 검색 결과 목록을 유효 본문으로 인정한다(AC-B-008-1 예외). 완화 범위는 **nav_shell 판정 면제뿐**이다 — 최소 길이 하한은 유지되어 빈 결과 페이지는 여전히 실패한다.
- **AC-B-014-2**: 명시성 판정은 **입력 URL로만** 한다. 임의 URL을 열었더니 사이트가 검색 페이지로 리디렉트했거나 우발적으로 검색 페이지가 나온 경우는 여전히 `validation_failed`다(응답 사후 재분류 금지).
- **AC-B-014-3**: 검색 결과 본문도 다른 챌린지 신호(WAF·동의 배너)가 있으면 그 사유로 실패한다. 검색 URL이라는 사실이 챌린지 판별을 무력화하지 않는다.
- **AC-B-014-4**: 검색 선언도 `source`·`verified_at` 의무와 20 항목 합산 상한(AC-B-010-15)을 진다. 누락·초과는 로드 실패(종료 코드 3)다. 등재 조건은 AC-B-012-6 을 승계한다 — R6 개정으로 robots 는 조건에서 빠지고 **정직한 UA 200 실측**이 남는다.

### US-B-015 — 자기선언 열린문 티어 (R6)

<!-- provenance: repo-fact -->

As a 리서처, I want to 페이지가 **스스로 밝힌** 다른 표현(JSON-LD 본문·피드·AMP·oEmbed·타 오리진 canonical)이 있으면 그것으로 본문을 받길 원한다, so that SPA 셸·네비게이션 껍데기 때문에 실제로 공개된 글을 놓치지 않는다. (J1)

> R2 는 `m.`·`amp.` 접두를 **맹목적으로 붙여 보는** 변형을 12건 중 0건으로 폐기했다. 이 US 는 그 경로의 부활이 아니라 정반대다 — 받은 HTML 안에 **문자로 적혀 있던 주소만** 따라간다.

- **AC-B-015-1**: 진입 조건은 **바이트는 받았는데 본문이 못 쓸 때**로 한정한다(`validation_failed` + 셸 신호, 또는 잘린 본문). 403·네트워크 실패에는 파싱할 HTML 이 없으므로 이 티어를 시도하지 않는다.
- **AC-B-015-2**: **선언이 없으면 요청을 만들지 않는다.** 선언이 하나도 없는 HTML 에 대한 이 티어의 네트워크 요청 수는 **0** 이며, 이는 동작이 아니라 **요청 카운터**로 검증한다 — 맹목 변형은 결과가 아니라 회선을 쓰는 것 자체가 위반이기 때문이다 (NG-10).
- **AC-B-015-3**: 후보 URL 은 예외 없이 `policy.check_url` 을 **새로** 통과해야 한다. 원본이 공개였다는 사실은 그 원본이 가리키는 주소의 안전을 보증하지 않는다 (NG-11).
- **AC-B-015-4**: 요청 예산은 2건이다. 취득한 대체 표현에서 링크를 다시 뽑지 않는다 (NG-5 재귀 부재).
- **AC-B-015-5**: 가져온 대체 표현도 `detect.classify` 를 그대로 통과해야 성공이다. 특히 **피드를 받았는데 요청한 문서가 그 안에 없으면 실패**다 — 같은 호스트의 다른 글을 돌려주고 성공이라 부르는 것이 이 티어의 가장 그럴듯한 거짓말이다 (NG-10).
- **AC-B-015-6**: 성공 시 `attempts[]` 에 `route="alternate"` 가 남고 `final_route` 로 구분된다. 어떤 선언을 따랐는지가 결과에 표기된다.

### US-B-016 — 명시한 목록의 병렬 취득 (R6)

<!-- provenance: user-fact -->

As a 리서처, I want to 내가 명시한 URL 목록을 한 번에 병렬로 가져오길 원한다, so that 근거 여러 건을 회수하는 데 걸리는 시간이 건수에 비례해 늘지 않는다. (J1, J4)

- **AC-B-016-1**: `fetch --batch <파일|->` 는 줄 단위 목록을 읽는다. 빈 줄·`#` 주석은 건너뛰고, 중복은 **순서를 유지한 채** 제거한다. 목록 상한은 50건이며 초과는 요청 전 exit 4 다.
- **AC-B-016-2**: 위치 인자 `url` 과 `--batch` 는 **상호 배타**다. 둘 다 주거나 둘 다 없으면 exit 4 — 무엇을 가져오라는 것인지 조용히 골라 잡지 않는다.
- **AC-B-016-3**: 페이싱을 새로 만들지 않는다. **같은 호스트의 URL 은 워커 수와 무관하게 직렬**이고 간격 하한 `MIN_HOST_INTERVAL_S` 를 지킨다 — 기존 `transport.host_gate` 를 그대로 통과시켜 얻는다. 배치가 자기 페이싱을 따로 구현하면 단건 경로와 두 벌이 되어 한쪽만 고쳐진다.
- **AC-B-016-4**: `--concurrency N` 은 `1..8`(기본 4)이며 **전역 워커 수만** 늘린다. 범위 밖은 exit 4.
- **AC-B-016-5**: 출력은 URL 당 NDJSON 1줄이고 스키마는 단건 `FetchResult` 와 동일하다. 부분 실패가 나머지를 중단시키지 않는다.
- **AC-B-016-6**: 종료코드는 전부 성공 0 / 하나라도 실패 1 / 실패가 **경계 사유뿐**이면 2 다.

### US-B-017 — 질의로 후보 URL 모으기 (R6)

<!-- provenance: user-fact -->

As a 리서처, I want to URL 을 이미 알지 못해도 질의로 공개 검색 소스에 물어 후보를 받길 원한다, so that 근거가 "우연히 아는 URL" 로 좁혀지지 않는다. (J1, J4)

> 이 US 는 `search:`(AC-B-014, **판정 전용·요청 없음**)를 건드리지 않는다. 별도 섹션 `search_sources:` 를 쓴다.

- **AC-B-017-1**: `search "<질의>"` 는 인덱스 `search_sources:` 에 선언된 소스에 병렬로 질의해 후보 URL 목록을 낸다. `--sources a,b,c` 로 부분 선택하며, 모르는 이름은 요청 전 exit 4 다.
- **AC-B-017-2**: 후보는 라운드로빈으로 섞은 뒤 dedupe 하고 `--max-results`(기본 10, **상한 25**)로 자른다. 절단은 인터리브 **후**에 한다 — 먼저 자르면 한 소스가 결과를 독식한다.
- **AC-B-017-3**: **취득한 본문의 링크를 다시 후보로 넣지 않는다.** 이것이 NG-5 개정판의 유일한 방벽이므로 동작이 아니라 **구조**로 강제한다: 후보 생성 모듈은 `fetcher`·`batch`·`extract`·`alternates` 를 임포트하지 않으며(동적 임포트 포함), 이를 AST 로 검증한다.
- **AC-B-017-4**: `--urls-only` 는 후보만 내고 **취득을 하지 않는다**. 이때 대상 URL 에 대한 요청 수는 0 이다.
- **AC-B-017-5**: 질의 치환은 기존 쿼리 **값 위치** 치환자 검증(AC-B-010-11 R5 개정)을 그대로 재사용하며, 질의는 퍼센트 인코딩되어 `&`·`=`·`/` 로 URL 구조를 바꿀 수 없다. 질의 길이 상한은 256자다.
- **AC-B-017-6**: `search_sources:` 등재 조건은 AC-B-012-6 을 승계한다 — **정직한 UA 로 200 + 실제 결과 실측 + `source` + `verified_at`**. 브라우저 UA 를 요구하는 SERP 는 등재하지 않는다: 등재해 놓고 런타임에만 다른 신원을 쓰면 실측이 거짓말이 된다 (NG-8·NG-13). 20 항목 합산 상한(AC-B-010-15)에 포함된다.
- **AC-B-017-7**: 소스가 **자기 기계장치를 결과처럼 내는** 경우는 선언 `exclude_hosts`(상한 8, 하위 도메인 포함)로 걷어낸다. 코드에 벤더 이름을 박지 않는다 — 이런 규칙은 벤더마다 다르고 시간이 지나면 바뀌므로, `source`·`verified_at` 옆에서 같은 절차로 리뷰되어야 한다.
- **AC-B-017-8**: 출력은 NDJSON 이고 **첫 줄이 검색 요약**(소스별 성패 + 후보 목록)이다. 소스 하나가 실패해도 나머지 결과를 낸다.

### US-B-018 — 수확률 기반 거짓 성공 차단 (R6)

<!-- provenance: repo-fact -->

As a 리서처, I want to 70만 자를 받아 226자를 건진 결과가 "성공" 으로 보고되지 않길 원한다, so that 돌파율이 실제 돌파 없이 오르지 않는다. (J2)

> 실측 근거는 `docs/r6-contract.md` §5 파생결함 1 — `search.naver.com` 이 200 으로 준 "검색 이용이 제한되었습니다" 안내문 328자가 `MIN_ARTICLE_CHARS` 를 넘겨 `ok=true` 로 계상됐다.

- **AC-B-018-1**: `MAIN_TAGS` 가 없는 문서에서는 컨테이너별 `텍스트 길이 / (링크 텍스트 길이 + 1)` 로 최상 서브트리를 고른다. 문서 전체보다 `DENSITY_GAIN` 배 이상 깨끗할 때만 채택한다 — 이득이 미미한데 좁히면 본문 일부를 조용히 버리는 쪽이 손해다.
- **AC-B-018-1b**: 후보는 **두 겹의 분량 하한**을 넘어야 한다 — 절대치(`MIN_ARTICLE_CHARS`)와 문서 본문 대비 비율(`MIN_COVERAGE`)이다. 비율 하한이 없으면 밀도 1위는 거의 항상 링크 없는 짧은 안내문이 된다: 2026-09-03 `bench --tier 1` 실측에서 `www.bankofamerica.com` 문서 전체 3,566자 중 625자짜리 앱스토어 안내가 채택돼 본문의 83%가 버려졌고, 그 결과 AC-B-018-3 에까지 걸려 **성공이 `validation_failed` 로 뒤집혔다**(`rate_http_only` 1.000 → 0.917). 고르는 것은 "가장 깨끗한 조각"이 아니라 "본문이 있는 자리"다.
- **AC-B-018-2**: 발행자의 명시적 선언(`<main>`/`<article>`)이 밀도 폴백보다 **앞선다**.
- **AC-B-018-3**: 큰 문서(`MIN_YIELD_HTML_CHARS` 이상)에서 추출량이 `MIN_YIELD_RATIO` 미만이면 `validation_failed` 다. 이 판정은 `len(extracted) < NAV_SHELL_MAX_CHARS` 일 때만 적용되어, **실측으로 성공이라 정해 둔 영역**(짧은 줄로만 이뤄진 진짜 본문 — 블로그 인덱스·이슈 목록·소스 코드 뷰)은 구조적으로 건드릴 수 없다.
- **AC-B-018-4**: 수확률 판정은 R5 검색 면제 **밖**에 있다. AC-B-014-3 의 "면제는 nav_shell 하나" 를 그대로 지킨다 — 선언된 검색 URL 이라도 결과 목록을 못 받았으면 성공이 아니다.

---

## Data Model

<!-- provenance: user-fact -->

> Python `dataclass` (frozen) 로 정의하며 JSON 직렬화가 1:1 대응한다. DB는 사용하지 않고 파일(JSONL/YAML)만 쓴다.

### FetchRequest
| 필드 | 타입 | 제약조건 | 설명 |
|------|------|----------|------|
| url | str | 필수, 스킴 `http` 또는 `https`, 길이 2048 이하 | 대상 URL |
| intent | str | `article`/`media`/`raw`, 기본 `article` | 추출 방식 선택 |
| timeout_s | float | `0 < t <= 60`, 기본 `20` | 요청 1건 상한 |
| allow_browser | bool | 기본 `false` | 브라우저 티어 허용 여부 (R1·R2에서는 `false` 강제, R3부터 `--allow-browser`로 opt-in) |
| max_attempts | int | `1..12`, 기본 `6` | 격자 시도 상한 |
| robots_mode | str | `off`/`advisory`/`enforce`, 기본 `off` | robots.txt 취급 모드 (R6, AC-B-003-6). 닫힌 집합 밖의 값은 `InvariantError` — 조용히 `off` 로 강등하지 않는다 |

### Attempt
| 필드 | 타입 | 제약조건 | 설명 |
|------|------|----------|------|
| route | str | `policy`/`phase0`/`http`/`browser`/`alternate` | 시도 계층. `alternate` 는 R6 자기선언 열린문 티어 (AC-B-015-6) |
| impersonate | str 또는 null | `profiles.yaml`의 후보 값 | TLS 지문 |
| referer | str 또는 null | URL 또는 null | 전송한 Referer |
| url_variant | str | `original`/`mobile`/`rss`/`json`/`oembed`/`amp` | 시도한 URL 변형 |
| status | int 또는 null | `100..599` 또는 null(네트워크 실패) | HTTP 상태 |
| elapsed_ms | int | `>= 0` | 소요 시간 |
| outcome | str | `success`/`challenge`/`wall`/`error`/`blocked` | 시도 결과 |
| rule | str 또는 null | `route="policy"`일 때만 non-null이며 값은 `PolicyVerdict.rule` 도메인 | 적용된 정책 규칙 |

`rule`은 정책 계층이 내린 `PolicyVerdict`를 시도 이력에 남기는 통로다. `FetchResult`는 최상위 필드를 늘리지 않으므로(응답 포맷 고정), 차단 규칙의 식별은 차단 판정이 기록되는 자리인 `attempts[0]`에서 이뤄진다. 이 값이 없으면 `scheme`·`private_range`·`redirect_hop` 세 SSRF 차단이 출력에서 모두 `policy_blocked` 하나로 붕괴해 회귀가 조용히 지나간다 (NG-10).

### FetchResult
| 필드 | 타입 | 제약조건 | 설명 |
|------|------|----------|------|
| url | str | 요청 URL 원문 | 입력 에코 |
| ok | bool | 필수 | 성공 여부 |
| content_markdown | str 또는 null | `ok=true`면 non-null | 추출된 본문 |
| metadata | object | `title`·`final_url`·`content_type`·`fetched_at` 필수 + `content_license`(선택, 원본이 명시한 경우에만 — AC-B-010-18) | `ok=true`면 필수 |
| failure_reason | str 또는 null | `ok=false`면 11종 중 하나 (non-null) | 실패 사유 |
| attempts | Attempt 배열 | 길이 `>= 1` | 시도 이력 |
| final_route | str 또는 null | Attempt.route와 동일 도메인 | 성공 경로 |

**불변식**: `ok=true`이면 `failure_reason=null`이고 `content_markdown`이 non-null이다. 위반은 프로그래밍 오류이며 예외를 던진다.

### WafVerdict
| 필드 | 타입 | 제약조건 | 설명 |
|------|------|----------|------|
| vendor | str | 9종 + `unknown_challenge` + `none` | 판정된 벤더 |
| confidence | float | `0.0..1.0` | 판정 신뢰도 |
| signals | str 배열 | 각 원소는 감지 규칙 ID | 판정 근거 |
| capabilities_needed | str 배열 | `js`/`tls`/`cookie_jar` 부분집합 | 돌파에 필요한 역량 |

### WafProfile (`profiles.yaml` 1 항목)
| 필드 | 타입 | 제약조건 | 설명 |
|------|------|----------|------|
| vendor | str | 고유 | 벤더 식별자 |
| detectors | object 배열 | 각 원소 `{id, kind, pattern, weight}` | 헤더·쿠키·본문·상태 규칙 |
| impersonate_candidates | str 배열 | 길이 `>= 1`, 우선순위 순 | TLS 후보 |
| impersonate_avoid | str 배열 | 중복 없음 | 회피 후보 |
| transform_order | str 배열 | url_variant 부분집합 | 변형 시도 순서 |
| fallback_order | str 배열 | route 부분집합 | 폴백 순서 |
| last_reviewed | date | ISO-8601 날짜 | 90일 초과 시 경고 |
| seeded_from | str 또는 null | `insane-search@<commit>` 형식 | 시드 출처 (ADR-003) |

**제약**: `detectors[].pattern`에 **호스트명·도메인 리터럴을 넣을 수 없다** (NG-9). 린트가 검사한다.

### ApiIndexEntry (`engine/api_index.yaml` 1 항목, R2)

| 필드 | 타입 | 제약조건 | 설명 |
|------|------|----------|------|
| host | str | 필수, 정확 일치 | 원문 URL의 호스트 |
| url_pattern | str | 필수, 정규식 | 적용 대상 — 입력 URL의 **경로(쿼리가 있으면 `경로?쿼리`)**에 매치한다 (R5 개정 — 실측: HN `/item?id=…` 처럼 식별자가 쿼리에 있는 플랫폼). 템플릿에 치환할 명명 캡처 그룹 포함 |
| endpoints | str 배열 또는 null | `endpoints`·`chain` 중 **정확히 하나**만 non-null | **순차로 시도하고 첫 유효 본문에서 멈추는** 단순 형태. 앞 항목이 404·빈 본문이면 다음 항목으로 넘어가고, 유효한 본문을 얻는 즉시 남은 항목은 요청하지 않는다 |
| chain | ChainStep 배열 또는 null | 길이 `1..2` (AC-B-010-8) | 앞 단계 응답에서 뽑은 값을 다음 요청에 넘기는 형태 |
| response_kind | str | `json` 또는 `html` | `html`이면 기존 추출기를 재사용한다 |
| content_pointer | str 또는 null | `response_kind="json"`이면 필수 | 본문이 있는 JSON 경로 (예: `items[].body`) |
| source | str | 필수, `https` URL | 해당 API의 **공식 문서** 주소. 출처 없는 항목은 로드 실패 |
| verified_at | str | 필수, `YYYY-MM-DD` | 마지막 실측 날짜 |

### ChainStep (`ApiIndexEntry.chain` 1 항목, R2)

| 필드 | 타입 | 제약조건 | 설명 |
|------|------|----------|------|
| request | str | 필수, 스킴·호스트가 **리터럴로 고정** (AC-B-010-12) | 요청 URL 템플릿 |
| response_kind | str | `json` 또는 `html` | 이 단계의 응답 형식 |
| select | str 또는 null | 마지막 단계가 아니면 필수 | 다음 단계로 넘길 **스칼라 1개**의 JSON 경로 (AC-B-010-9) |
| value_pattern | str 또는 null | `select`가 non-null이면 필수, `^`·`$` 앵커 필수 | 뽑은 값의 허용 형태 (AC-B-010-10) |
| bind | str 또는 null | `select`가 non-null이면 필수 | 다음 템플릿에서 쓸 이름. **경로 세그먼트 1개**로만 치환된다 (AC-B-010-11) |

**제약**: `url_pattern`의 캡처 그룹과 `bind` 이름만이 템플릿 치환의 입력이다. 응답에서 온 값이 스킴·호스트·쿼리 구조를 바꿀 수 없다 — 쿼리 치환자는 응답 유래 값이 존재하지 않는 `chain` 없는 `endpoints` 항목에서만 허용된다 (AC-B-010-11 R5 개정). 인덱스 전체 항목 수는 `entries` 와 `search` 를 **합산해 20 이하**다 (AC-B-010-15, R5 개정).

### SearchDeclaration (`engine/api_index.yaml` `search:` 1 항목, R5)

| 필드 | 타입 | 제약조건 | 설명 |
|------|------|----------|------|
| host | str | 필수, 정확 일치 | 검색 엔드포인트의 호스트 |
| url_pattern | str | 필수, 정규식 | 입력 URL의 `경로?쿼리` 에 매치하면 **명시적 검색 URL**로 인정한다 (AC-B-014-1) |
| source | str | 필수, `https` URL | 해당 검색 엔드포인트의 공식 문서 주소 |
| verified_at | str | 필수, `YYYY-MM-DD` | 마지막 실측 날짜 |

**제약**: 선언은 검증기 판정(AC-B-008-1 예외)에만 쓰이며 **요청을 만들지 않는다** — 어떤 URL 조립·치환도 하지 않는다. `source`·`verified_at` 누락은 로드 실패(종료 코드 3, AC-B-010-15 승계).

### SearchSource (`engine/api_index.yaml` `search_sources:` 목록, R6)

위 `SearchDeclaration` 과 **다른 섹션**이다. 그쪽은 판정 전용(요청 없음)이고, 이쪽은 질의를 실제로 던져 후보 URL 을 받아 온다. 분리한 이유는 us-b-014 동결(AC-B-014-1)을 오염시키지 않기 위해서다.

| 필드 | 타입 | 제약조건 | 설명 |
|------|------|----------|------|
| name | str | 필수, 인덱스 내 유일 | `--sources` 로 고르는 이름 |
| host | str | 필수, `query_template` 의 netloc 과 일치 | 소스 호스트 |
| kind | str | `json`/`html` | 응답 파싱 방식 |
| query_template | str | 필수, `https`, 쿼리 **값 위치** `{query}` 1개 | 질의 치환 URL. 검증기는 AC-B-010-11(R5 개정)을 그대로 재사용한다 |
| result_pointer | str 또는 null | `kind=json` 에서 필수 | 결과 배열의 점 표기 경로 |
| link_pointer / title_pointer | str 또는 null | 항목 상대 경로 | 항목당 URL·제목. 짝지을 수 없으면 제목은 비운다 — 어긋난 제목은 없는 정보보다 나쁘다 (NG-10) |
| result_link_pattern | str 또는 null | `kind=html` 에서 필수, 캡처 그룹 1개 | HTML 에서 링크를 뽑는 정규식 |
| link_transform | str 또는 null | `percent` | 래핑된 링크를 푸는 방식. 벤더 전용 디코더는 추가하지 않는다 |
| exclude_hosts | list[str] 또는 null | 최대 8, 소문자 호스트명 | 후보에서 걷어낼 호스트(하위 도메인 포함) — 소스가 자기 기계장치를 결과처럼 낼 때 (AC-B-017-7) |
| source | str | 필수, `https` URL | 그 검색 API 를 공개로 문서화한 페이지 |
| verified_at | str | 필수, `YYYY-MM-DD` | 정직한 UA 로 200 + 실제 결과를 확인한 날짜 |

**제약**: `entries` + `search` + `search_sources` **합산 20 항목** 상한(AC-B-010-15). 위반은 로드 실패(종료 코드 3).

### Observation (`observations.jsonl` 1줄)
| 필드 | 타입 | 제약조건 | 설명 |
|------|------|----------|------|
| ts | str | ISO-8601 UTC | 기록 시각 |
| host | str | 정규화된 host | 소문자 |
| path | str | 정규화된 path (query·fragment 제거) | 경로만 |
| waf_vendor | str | WafVerdict.vendor | 판정 벤더 |
| route | str | Attempt.route | 성공 계층 |
| impersonate | str 또는 null | 후보 값 | TLS 지문 |
| url_variant | str | url_variant 값 | 성공한 변형 |
| outcome | str | `success` 고정 | 경계 위반 경로는 기록 금지 |

**허용 필드 화이트리스트**: 위 8개 키만 허용한다. 다른 키의 기록 시도는 `ObservationSchemaError`로 거부된다 (NG-4).

### BatteryFile (`battery.yaml` 헤더)
| 필드 | 타입 | 제약조건 | 설명 |
|------|------|----------|------|
| role | str | `production` 또는 `fixture` | 거버넌스 적용 범위 결정. 출하 배터리는 `production` 고정 |
| entries | BatteryEntry 배열 | 길이 `>= 1` | 항목 목록 |
| vendor_scope | str 배열 | 선택. 값은 WAF 감지기에 존재하는 벤더명 | G-1을 적용할 벤더 범위. **생략하면 벤더 9종 전체**가 범위다 — 키 누락이 범위를 줄이는 가장 싼 방법이 되지 않게 한다 (G-8) |
| vendor_scope_reason | str | `vendor_scope` 가 있으면 **필수**, 길이 `>= 1` | 범위를 좁힌 사유. 사유 없는 축소는 exit `3` (G-8) |

### BatteryEntry / Expected (`battery.yaml`)
| 필드 | 타입 | 제약조건 | 설명 |
|------|------|----------|------|
| id | str | 고유, `^[a-z0-9-]+$` | 항목 ID |
| url | str | http/https | 대상 |
| tier | int | `1` 또는 `2` | 등급 |
| waf_expected | str | 벤더 식별자 또는 `none` | 정답 라벨 (A2 판별 정확도 측정용) |
| added_reason | str | 비어있지 않음 | 왜 배터리에 있는가 |
| negative_case | str 또는 null | `auth_wall`/`paywall`/`waf_challenge` | 음성 케이스면 기대 실패 사유 (G-3) |
| expected | Expected | `negative_case=null`이면 필수 | 정답 대조 기준 |

**Expected**: `{title_contains, body_contains, min_chars, normalized_hash}` — 네 필드 중 **최소 1개가 non-null**이어야 한다.

### BenchRun (`bench/history.jsonl` 1줄)
| 필드 | 타입 | 제약조건 | 설명 |
|------|------|----------|------|
| ts | str | ISO-8601 UTC | 실행 시각 |
| engine | str | `open-reach@<version>` | 측정 대상 |
| battery_hash | str | sha256 hex | 배터리 동일성 |
| runs | int | `>= 1` | 반복 횟수 |
| total / passed / failed | int | `total = passed + failed` | 집계 |
| rate_median | float | `0.0..1.0` | 중앙값 돌파율 |
| by_vendor / by_route / by_reason | object | `{키: 정수}` | 분해 |
| regression | str | `none`/`regressed`/`incomparable` | dead-band 3%p 적용 |

### PolicyVerdict
| 필드 | 타입 | 제약조건 | 설명 |
|------|------|----------|------|
| allowed | bool | 필수 | 허용 여부 |
| rule | str | `scheme`/`private_range`/`robots`/`rate_limit`/`browser_disabled`/`redirect_hop` | 적용된 규칙 |
| detail | str | 비어있지 않음 | 사람이 읽는 사유 |

### 파일 저장소 (인덱스 대체)

| 파일 | 형식 | 접근 패턴 | 동시성 |
|------|------|----------|--------|
| `observations.jsonl` | JSONL, append-only | 순차 읽기 후 메모리 집계 | 배타 생성 락 + append |
| `bench/history.jsonl` | JSONL, append-only | 마지막 N줄 비교 | 배타 생성 락 + append |
| `profiles.yaml` | YAML | 전체 로드 | 임시 파일 + rename (원자적) |

---

## CLI 계약 (API Contract)

<!-- provenance: user-fact -->

> HTTP 엔드포인트가 없으므로 **CLI 서브커맨드가 외부 계약**이다. 모든 서브커맨드는 `python -m open_reach.engine <sub> ...` 로 호출하며,
> 성공 시 stdout에 **JSON 1개**(또는 명시된 최종 라인)를 출력하고 진단 메시지는 stderr로 보낸다.

**공통 종료 코드**

| 코드 | 의미 |
|------|------|
| 0 | 성공 (또는 측정 불가를 정상 보고) |
| 1 | 일반 실패 (분류된 `failure_reason` 포함) |
| 2 | 경계 도달 — `auth_wall` / `paywall` / `policy_blocked` |
| 3 | 게이트 위반 — 배터리 거버넌스 위반, 음성 케이스 오분류 |
| 4 | 사용 오류 — 인자 형식 오류, 파일 없음, 출력 파일 선점 |

### `fetch <url>`

옵션: `--intent article|media|raw`, `--timeout <초>`, `--max-attempts <N>`, `--allow-browser`, `--api-index <경로>`, `--robots off|advisory|enforce`, `--respect-robots`

  `--robots` 는 AC-B-003-6 의 모드를 고른다. 기본값은 `off`. `--respect-robots` 는 `--robots enforce` 의 별칭이며, 두 플래그가 **서로 다른 것을 지시하면 요청을 시작하기 전에 exit 4** 다 — 모호한 입력을 어느 한쪽으로 조용히 해석하는 것이 robots 에서는 가장 나쁜 실패다 (NG-10).

  `--allow-reader` 는 도입하지 않는다 — US-B-013 은 철회됐다 (US-B-013 철회 노트 + R6 정정 참조).

- **Auth**: 없음 — 이 도구는 어떤 자격증명도 받지 않고 저장하지 않는다 (NG-4).
- **Request**: 위치 인자 `url` (필수), 옵션은 `FetchRequest` 필드와 1:1 대응.
  `--api-index <경로>`는 Phase 0 공개 API 인덱스(`ApiIndexEntry` 목록)의 대체 파일을 지정한다. 기본값은 출하 인덱스이며, 이 옵션은 인수 테스트가 픽스처 인덱스를 지정하는 통로다 (`bench --battery`와 동일한 구조). 지정 파일이 AC-B-010-8·10·12·15의 로드 시점 제약을 하나라도 어기면 **요청을 시작하기 전에** exit 3으로 중단한다.
- **Validation**: 스킴 allowlist(`http`/`https`), 길이 2048 이하, DNS 해석 후 사설·루프백·링크로컬·CGNAT 대역 차단, `--timeout` 은 `0 < t <= 60`, `--max-attempts` 는 `1..12`.
- **Response 0**: `FetchResult` JSON (`ok=true`).
- **Response 1**: `FetchResult` JSON (`ok=false`, `failure_reason`이 `waf_challenge`·`rate_limited`·`not_found`·`server_error`·`network`·`validation_failed`·`unsupported`·`unknown` 중 하나).
- **Response 2**: `FetchResult` JSON (`ok=false`, `failure_reason`이 `auth_wall`·`paywall`·`policy_blocked` 중 하나).
- **Response 3**: `{"error": {"code": "usage", "message": "..."}}` — API 인덱스 로드 실패 (chain 길이 초과, `value_pattern` 누락, 스킴·호스트 바인딩, 항목 수·출처 필드 위반). 네트워크 요청 0건.
- **Response 4**: `{"error": {"code": "usage", "message": "..."}}`.
- **테스트 케이스**:
  - 공개 HTML 문서 → exit 0, `content_markdown` 200자 이상, `metadata.title` non-null
  - 로그인월 픽스처 → exit 2, `failure_reason="auth_wall"`, 판정 후 추가 attempt 없음
  - 페이월 픽스처(중략 마커 + `isAccessibleForFree=false`) → exit 2, `failure_reason="paywall"`
  - WAF 챌린지 픽스처(200 + `Just a moment` 제목) → exit 1, `failure_reason="waf_challenge"`
  - 404 픽스처 → exit 1, `failure_reason="not_found"`
  - 429 + `Retry-After` 픽스처 → exit 1, `failure_reason="rate_limited"`, 재시도 총량이 `max_attempts` 이하
  - `http://127.0.0.1:1/x` → exit 2, `failure_reason="policy_blocked"`, `attempts[0].route="policy"`, 네트워크 요청 0건
  - `file:///etc/passwd` → exit 2, `policy_blocked` (스킴 위반)
  - 공개에서 사설로 리디렉션하는 픽스처 → exit 2, `policy_blocked`, `attempts[0].rule="redirect_hop"`
  - `--timeout 0` → exit 4
  - Phase 0 라우팅 음성 케이스 8종 (`tests/acceptance/us-b-010-api-routing-negative.sh`) — AC-B-010-8·9·10·11·12·13·14를 각각 **가드가 없으면 실패하는** 형태로 고정한다. "요청하지 않았다"는 픽스처 서버의 경로별 요청 카운터(`/_hits`)로 단언하며, 모든 케이스에서 응답이 지시한 목적지(`/api/evil`)의 요청 수는 0이어야 한다.

### `fetch --batch <파일|->`

옵션: `--batch <파일|->`, `--concurrency <N>`, 그 외 `fetch` 의 옵션 전부 (목록 전체에 동일하게 적용)

- **Request**: `--batch` 와 위치 인자 `url` 은 상호 배타다 (AC-B-016-2). `-` 는 표준 입력을 읽는다.
- **Validation**: 줄당 URL 1개, 빈 줄·`#` 주석 무시, 순서 유지 dedupe, 목록 상한 50건, `--concurrency` 는 `1..8`(기본 4). 위반은 **요청 전** exit 4.
- **Response**: URL 당 NDJSON 1줄, 스키마는 단건 `FetchResult` 와 동일. 부분 실패가 나머지를 중단시키지 않는다.
- **종료코드**: 전부 성공 0 / 하나라도 실패 1 / 실패가 경계 사유뿐이면 2 (AC-B-016-6).
- **페이싱**: 같은 호스트의 URL 은 워커 수와 무관하게 직렬이며 `MIN_HOST_INTERVAL_S` 하한을 지킨다 — `transport.host_gate` 를 그대로 통과시켜 얻는다 (AC-B-016-3).
- **테스트 케이스**:
  - 같은 호스트 2건 → 요청 시각 간격 ≥ `MIN_HOST_INTERVAL_S`, 겹치는 in-flight 없음
  - 다른 호스트 2건 → 병렬 실행
  - 51건 목록 → exit 4, 네트워크 요청 0건
  - `--concurrency 0` / `9` → exit 4
  - 성공 1 + 경계 1 → exit 2 · 성공 1 + 네트워크 실패 1 → exit 1

### `search "<질의>"`

옵션: `--max-results <N>`, `--sources <a,b,c>`, `--urls-only`, `--concurrency <N>`, `--api-index <경로>`

- **Auth**: 없음 — 키를 요구하는 검색 API 는 등재하지 않는다 (NG-4).
- **Request**: 위치 인자 `query` (필수, 256자 이하). 기본은 선언된 소스 **전부**에 팬아웃.
- **Validation**: `--max-results` 는 `1..25`(기본 10), 모르는 소스 이름은 exit 4, 질의는 퍼센트 인코딩되어 URL 구조를 바꿀 수 없다 (AC-B-017-5).
- **Response 0**: NDJSON. **첫 줄이 검색 요약**(소스별 성패 + 후보 목록), 이어서 `--urls-only` 가 아니면 후보당 `FetchResult` 1줄.
- **Response 1**: 후보가 0건 — 소스가 전부 실패했거나 결과가 없다. 없는 후보를 지어내지 않는다 (NG-10).
- **Response 3**: 인덱스 로드 실패 (`search_sources:` 제약 위반). 네트워크 요청 0건.
- **Response 4**: 인자 오류.
- **테스트 케이스**:
  - `--urls-only` → 후보 URL 에 대한 요청 수 **0**, NDJSON 정확히 1줄
  - 두 소스가 같은 URL 을 낼 때 → 후보에 1회만 (먼저 낸 소스로 귀속)
  - 소스 하나가 500 → 나머지 후보는 그대로 나오고 요약에 실패가 기록된다
  - `--max-results 26` / 모르는 소스 이름 → exit 4
  - 취득 본문에 링크가 가득해도 후보가 늘지 않는다 (AC-B-017-3, 구조·동작 양쪽)

### `bench`

옵션: `--tier 1|2`, `--runs <N>`, `--no-browser`, `--shuffle`, `--holdout`, `--battery <경로>`

- **Auth**: 없음.
- **Request**: 모두 옵션. 기본값 `--tier 1 --runs 3`. `--holdout`은 `bench/holdout.yaml`을 대상으로 하며 `--tier`와 함께 쓸 수 없다.
  `--battery <경로>`는 대체 배터리 파일을 지정하며 `--holdout`과 함께 쓸 수 없다 (인수 테스트가 픽스처 배터리를 지정하는 통로).
- **Validation**: `--runs` 는 `1..9`, 배터리 파일 존재, 거버넌스 사전 검사.
  거버넌스 적용 범위는 배터리 파일 헤더의 `role` 이 결정한다 — `role: production` 이면 G-1·G-3·G-4·G-6·G-8 전부, `role: fixture` 이면 G-3·G-4·G-6 만 검사한다(벤더 커버리지 G-1과 그 범위 선언 G-8은 출하 배터리의 요건이므로).
  `--tier`/`--holdout` 로 지정되는 출하 배터리(`bench/battery.yaml`, `bench/holdout.yaml`)는 `role: production` 이어야 하며, 아니면 exit `4`다 — 출하 배터리를 fixture 로 강등해 G-1을 회피하는 경로를 막는다.
- **Response 0**: `by_vendor` / `by_route` / `by_reason` 분해 블록 + 마지막 줄 `BENCH_RESULT: rate=<f> total=<n> passed=<n> failed=<n>`.
- **Response 3**: 거버넌스 위반 또는 음성 케이스 오분류. stderr에 위반 규칙 ID(`G-1`·`G-3`·`G-4`·`G-6`·`G-8`)를 명시.
- **Response 4**: 인자 오류 (`--tier`와 `--holdout` 동시 지정, `--battery`와 `--holdout` 동시 지정, 출하 배터리의 `role` 이 `production` 이 아님).
- **테스트 케이스**:
  - 정상 배터리 → exit 0, 마지막 줄이 `BENCH_RESULT:` 로 시작, 분해 3종이 그 앞에 존재
  - 벤더 1종이 1개뿐인 배터리 → exit 3, stderr에 `G-1`
  - 음성 케이스 0건 배터리 → exit 3, stderr에 `G-3`
  - `expected` 누락 항목 → exit 3, stderr에 `G-4`
  - 음성 케이스가 success로 분류됨 → exit 3 (돌파율과 무관)
  - `--runs 0` → exit 4
  - 동일 배터리 `--shuffle` 실행 결과가 순서 실행과 3%p 이내

### `compare`

옵션: `--tier 1|2`, `--battery <경로>`, `--original-cmd <커맨드>`, `--out <경로>`

- **Auth**: 없음.
- **Request**: `--original-cmd`는 원본 실행 커맨드(기본값은 설치 감지). `--battery`는 대체 배터리 파일, `--out`은 증적 파일 경로(기본값 `bench/compare-<UTC타임스탬프>.json`).
- **Validation**: 배터리 존재, 출력 파일명 충돌 없음.
- **Response 0**: `{status, open_reach, original, evidence, reason}` JSON + `bench/compare-<ts>.json` 저장. `evidence`는 `original_commit`·`ran_at`·`os`·`arch`·`python`·`battery_hash` 6개 필드를 갖는다.
- **Response 4**: 출력 파일이 이미 존재하거나(덮어쓰지 않는다) 배터리 파일이 없음.
- **테스트 케이스**:
  - 원본 미설치 → exit 0, `status="unmeasurable"`, `reason` non-null
  - 정상 → exit 0, `status="measured"`, `evidence` 6개 필드 전부 non-null
  - 출력 파일 선점 → exit 4, 기존 파일 내용 불변

### `baseline <샘플파일>`

- **Auth**: 없음.
- **Request**: URL 1줄씩 담긴 텍스트 파일 경로 (A0 측정 표본).
- **Validation**: 파일 존재, 각 줄이 `fetch` 와 동일한 URL 검증 규칙 통과, 최대 200줄.
- **Response 0**: `{total, failed, fail_rate, by_reason}` JSON — 표준 HTTP 클라이언트(임퍼소네이션 없음)만 사용한 실패율.
- **Response 4**: 파일 없음 또는 200줄 초과.
- **테스트 케이스**: 픽스처 3건(성공 1 + 404 1 + 로그인월 1) → `fail_rate` 가 `0.66`~`0.67`, `by_reason`에 `not_found`·`auth_wall` 각 1건

### `refresh`

옵션: `--dry-run`

- **Auth**: 없음.
- **Request**: 옵션만.
- **Validation**: `observations.jsonl` 존재 여부(없으면 정상 종료), `profiles.yaml` 쓰기 권한.
- **Response 0**: unified diff 텍스트 + 갱신된 벤더 수. `--dry-run`은 파일을 수정하지 않는다.
- **Response 4**: `profiles.yaml` 파싱 실패.
- **테스트 케이스**:
  - 관측 0건 → exit 0, `no observations` 출력, 파일 내용 불변
  - 관측 존재 → exit 0, diff 출력, `last_reviewed` 갱신
  - `--dry-run` → 파일 내용 불변
  - 경계 위반(`auth_wall`) 관측이 섞여 있어도 후보 순서에 반영되지 않음

### `explain <url>`

- **Auth**: 없음. **네트워크 요청을 보내지 않는다** (계획만 출력).
- **Request**: 위치 인자 `url`.
- **Validation**: `fetch`와 동일한 URL 검증.
- **Response 0**: `{policy, plan, waf_hint}` JSON. `plan`의 각 원소는 `{route, impersonate, url_variant, order}`.
- **Response 2**: 정책 차단 URL — `policy.allowed=false`.
- **테스트 케이스**: 공개 URL → exit 0, `plan` 길이 1 이상 / 사설 IP → exit 2 / 잘못된 스킴 → exit 2

### 에러 응답 포맷 (Error Response Format)

실패 출력은 두 형태뿐이며 다른 형태를 만들지 않는다.

```json
{"ok": false, "failure_reason": "auth_wall", "attempts": [], "url": "", "metadata": null, "content_markdown": null, "final_route": null}
```

```json
{"error": {"code": "usage", "message": "--timeout must be > 0 and <= 60"}}
```

`error.code` 는 `usage` 와 `internal` 두 값만 갖는다. `internal`은 불변식 위반이며 스택 트레이스를 stderr에 남긴다.

### 실패 사유 분류 (11종, 닫힌 집합)

| 사유 | 의미 | 종료 코드 |
|------|------|----------|
| `auth_wall` | 로그인 필요 — 시도 중단 (NG-1) | 2 |
| `paywall` | 유료 콘텐츠 — 시도 중단 (NG-2) | 2 |
| `policy_blocked` | 우리 정책이 차단 (robots 거부, 사설 대역, 브라우저 비활성) | 2 |
| `waf_challenge` | WAF 챌린지에서 최종 실패 | 1 |
| `rate_limited` | 429 또는 `Retry-After` — backoff 후 중단 | 1 |
| `not_found` | 4xx (404·410 등) | 1 |
| `server_error` | 5xx | 1 |
| `network` | DNS·TLS·타임아웃 | 1 |
| `validation_failed` | 응답은 받았으나 기대 정답 대조 실패 (배터리 전용) | 1 |
| `unsupported` | 구조적 미지원 (예: `browser_required`) | 1 |
| `unknown` | 위 어디에도 해당하지 않음 — 비율 10% 이하가 게이트 (SC-4) | 1 |

---

## Constraints (제약 · 비기능 요구 / Non-Functional Requirements)

<!-- provenance: user-fact -->

### 성능

- `fetch` 단건 상한: 기본 `--timeout 20`초 곱하기 `--max-attempts 6` → **총 벽시계 상한 120초**. 상한 초과 시 `network`로 종료한다.
- 호스트별 **동시성 1**, 동일 호스트 연속 요청 최소 간격 `1.0초`. 429 수신 시 `Retry-After` 값을 존중하고, 값이 없으면 지수 백오프(base 1초, 최대 30초, 최대 3회) 후 중단한다.
- `bench --tier 1 --runs 3` (50 URL 상한) 벽시계 상한: **30분**. 초과 시 부분 결과를 기록하고 `regression="incomparable"`로 표시한다.
- 관측 로그 집계는 파일 전체를 메모리에 올린다. `observations.jsonl` 상한 **50MB** — 초과 시 오래된 줄부터 회전(`observations.1.jsonl`)한다.
- 회귀 판정 dead-band **3%p** — 그 안의 변동은 `regression="none"`이다.

### 보안

- **자격증명을 취급하지 않는다.** 인증 관련 CLI 옵션·환경변수·설정 파일을 제공하지 않는다. 사용자 브라우저 프로필이나 쿠키 저장소를 읽지 않는다 (NG-4, NG-13).
- **SSRF 차단 (fail-closed)**: 스킴 allowlist(`http`/`https`) → DNS 해석 → 사설(RFC1918)·루프백·링크로컬(169.254/16)·CGNAT(100.64/10)·IPv6 ULA와 링크로컬 차단 → **리디렉션 매 홉 재검사**. `169.254.169.254` 등 클라우드 메타데이터 주소는 명시 차단 목록에 둔다. 판정 불가 시 **차단**한다. 단 DNS 조회 자체가 NXDOMAIN·타임아웃으로 실패한 경우는 연결을 시도하지 않되 `network`로 분류한다 — 차단 여부를 판정할 대상 자체가 없으므로 정책 위반이 아니다 (AC-B-002-3).
- **테스트 픽스처 예외 (유일한 예외)**: `OPENREACH_FIXTURE_BASE` 환경변수가 설정되어 있으면, 그 값이 가리키는 `scheme://host:port` **정확히 하나**만 사설·루프백 대역 차단에서 제외한다. 인수 테스트가 로컬 픽스처 서버(`127.0.0.1:<임의 포트>`)를 대상으로 실제 HTTP 경로를 검증하기 위한 통로이며, 다음 네 조건이 함께 성립해야 한다.
  - **오리진 완전 일치**: 스킴·호스트·포트가 모두 같아야 한다. 포트가 다른 루프백 주소(`127.0.0.1:1` 등)는 계속 차단된다.
  - **매 홉 적용**: 리디렉션 홉 검사는 그대로 수행하되, 각 홉에도 동일한 오리진 완전 일치 규칙으로 판정한다. 공개→사설 리디렉션은 여전히 `redirect_hop`으로 차단된다 (AC-B-003-5 불변).
  - **메타데이터 우선**: `169.254.169.254` 등 명시 차단 목록은 이 예외보다 항상 우선한다.
  - **자격증명 무관**: 이 변수는 대상 오리진만 지정하며 인증 정보를 담지 않는다 (NG-4 미저촉).

  변수가 없으면 예외는 존재하지 않는다 — 즉 배포 실행의 기본값은 "루프백 전면 차단"이다.
- **본문 미보관**: 취득 본문을 디스크에 캐시하지 않고 관측 로그에 기록하지 않는다 (NG-12).
- **로그 마스킹**: 관측 로그는 허용 필드 화이트리스트로만 기록한다. `Set-Cookie`·`Authorization`·`Cookie`·요청 본문·응답 본문은 어떤 필드로도 기록되지 않는다.
- **의존성 allowlist**: CAPTCHA 해결 서비스 SDK, 프록시 풀, 지문 생성 바이너리는 설치 금지 목록에 두고 코드 스캔 게이트가 검사한다 (NG-3, NG-6, ADR-006).
- **브라우저 티어(R3)**: 매 실행 **임시 프로필**을 생성하고 LIFO GracefulShutdown으로 정상 종료·크래시·SIGINT 모두에서 삭제한다. 세션을 실행 간 재사용하지 않는다.
- **robots.txt 는 모드로 다룬다 (R6 개정, 사용자 승인).** 기본값은 `off` — 조회하지 않는다. 판정을 받아 놓고 무시하는 것이 **아니다**: 요청이 나가면 상대 서버는 이미 그것을 봤으므로, 약속은 "따르지 않는다"가 아니라 "**조회하지 않는다**"이며 요청 수 0 으로 검증한다. `enforce`(`--respect-robots`)에서만 `Disallow` 가 `policy_blocked` 로 중단시키고, 이때 조회 자체가 실패하면 해당 호스트의 기본 정책(허용)을 따르되 사유를 관측에 남긴다. `advisory` 는 조회·보고하되 차단하지 않는다.
  - **왜 뒤집었나**: 잔여 도달력 격차의 실질 전부가 자발적 robots 준수였다(`docs/r1-report.md` 원본 64/70 vs 60/70 — 격차 4건 중 robots 자발 포기 2건, 실제 돌파력 격차 0건). 사용자 승인 아래 도달력을 택했다.
  - **바뀌지 않는 것**: robots 를 보지 않는 것과 신원을 속이는 것은 다른 일이다. 특정 AI UA 만 허용하는 곳에 그 UA 를 참칭하는 경로는 도입하지 않는다 (NG-13, US-B-013 철회 근거 유지). 호스트당 동시성 1 과 `MIN_HOST_INTERVAL_S=1.0` 하한도 모드와 무관하게 유지된다 — robots 를 안 본다고 상대 서버를 두드리는 속도까지 올리지는 않는다.

### 관측성 (로깅)

- 모든 로그는 **JSONL append-only**. 사람이 읽는 진단은 stderr, 기계가 읽는 결과는 stdout으로 분리한다.
- 파일: `observations.jsonl`(성공 경로 학습), `bench/history.jsonl`(측정 이력), `bench/compare-<ts>.json`(SC-1 증적).
- **상태 파일 위치**: `OPENREACH_STATE_DIR` 환경변수가 있으면 그 디렉토리, 없으면 저장소 루트를 기준으로 한다.
  **지문표 위치**: `OPENREACH_PROFILES` 환경변수가 있으면 그 파일, 없으면 `skills/open-reach/engine/profiles.yaml`.
  두 변수는 테스트 격리 전용이며 자격증명·인증과 무관하다 (보안 절의 '자격증명 미취급'을 위반하지 않는다).
- 모든 실패는 분류된 사유 + 시도 이력과 함께 보고한다. 조용한 실패 경로는 존재하지 않는다 (NG-10).
- append는 원자적으로 수행한다 — 배타 생성 락 파일 확보 후 `O_APPEND` 단일 write.

### 이식성

- 지원 OS: Windows 11 / macOS / Linux. 경로는 `pathlib`만 사용하고 셸 확장에 의존하지 않는다.
- Python `3.11` 이상 (`tomllib`·`ExceptionGroup` 사용). 개발 환경은 3.13.3.
- 신규 설치가 필요한 런타임 의존성은 `curl_cffi` 하나이며 사전빌드 휠로 컴파일러 없이 설치된다.

---

## E2E Scenarios

| ID | Scenario | Source (User Story) | Priority | Steps |
|----|----------|--------------------|----------|-------|
| E2E-001 | 공개 문서 조회 성공 | US-B-001, US-B-008 | high | 1. 픽스처 서버 기동 2. `fetch <public>` 3. exit 0 · `ok=true` 확인 4. `content_markdown` 200자 이상 · 스크립트 텍스트 부재 확인 |
| E2E-002 | 경계 도달 시 즉시 중단 | US-B-003 | high | 1. `fetch <login-wall>` 2. exit 2 · `auth_wall` 확인 3. 판정 이후 추가 시도 없음 확인 4. 관측 로그에 해당 경로 미기록 확인 |
| E2E-003 | SSRF 차단 | US-B-003 | high | 1. `fetch http://127.0.0.1:1/x` 2. exit 2 · `policy_blocked` 3. `attempts[0].route="policy"` 4. 공개에서 사설로 리디렉션하는 픽스처도 동일 차단 |
| E2E-004 | 분류된 실패 보고 | US-B-002, US-B-008 | high | 1. 404·429·챌린지 픽스처 각각 `fetch` 2. `failure_reason`이 11종 중 하나 3. `attempts` 비어있지 않음 |
| E2E-005 | 돌파율 산출 + 거버넌스 | US-B-004 | high | 1. 정상 배터리 `bench` → `BENCH_RESULT` + 분해 3종 2. G-1 위반 배터리 → exit 3 3. 음성 케이스 오분류 → exit 3 |
| E2E-006 | 관측에서 재사용, 그리고 갱신 | US-B-006, US-B-007 | medium | 1. 성공 `fetch` 2. `observations.jsonl` 1줄 증가 · 금지 필드 부재 3. 재조회 시 직전 경로가 `attempts[0]` 4. `refresh` → diff 출력 · `last_reviewed` 갱신 |

---

## Round 경계 (구현 계약의 범위)

| Round | 이 SPEC에서의 지위 |
|-------|-------------------|
| **R1** | `fetch`(T1 HTTP 경로) · `explain` · `baseline` · `bench` · `compare` · 정책 가드 · 검증기 · 사유 분류 · 관측 스키마 · 본문 추출 — **위 AC 전부가 구현 계약이다** |
| **R2** | **US-B-009**(벤더 표본 확보와 감지 정확도) · **US-B-010**(Phase 0 공개 API 라우팅, 2-hop 포함) — **위 AC 22종이 구현 계약이다.** SC-8·SC-9가 게이트다 |
| **R3** | 브라우저 티어(**A8 4항 판정 통과 시에만**) · 경로 재사용 우선순위 · `refresh` · holdout · 설치 시험 · SKILL.md 패키징 |
| **R4** | 마켓플레이스 등록 · `last_reviewed` 노후 경고 · 운영 문서 |
| **R5** | **US-B-012**(Phase 0 공개 플랫폼 어댑터 확장 — 실측 확정: HN·Bluesky 등재, Naver·Reddit·Threads·Mastodon 미등재, AC-B-012-6) · **US-B-013**(**철회** — `r.jina.ai` robots 전면 Disallow) · **US-B-014**(명시적 검색 URL 본문 인정, AC-B-008-1 예외) — 근거·경계는 `docs/r5-contract.md`. 종료 조건은 `rate_http_only` 무회귀 + 각 어댑터 인수 테스트 green |
| **R6** | **robots 정책 모드화**(AC-B-003-6 — 기본 `off`, `--respect-robots` 로 복원) + 그에 따른 SC-9·AC-B-010-3·-13·AC-B-012-6·AC-B-014-4·NG-5 개정. 사용자 승인(2026-09-02) 아래 경계 2건을 완화한 라운드이며 **완화 범위를 정확히 고정하는 것**이 계약이다: robots 만 빠지고 SSRF(NG-11)·경계 판정(NG-1·2·3)·신원(NG-13)은 어느 모드에서도 빠지지 않는다. 함께 신설: **US-B-015**(자기선언 열린문 티어 — `route="alternate"`) · **US-B-016**(`fetch --batch` 병렬 취득) · **US-B-017**(`search` 질의→후보, `search_sources:` 섹션) · **US-B-018**(수확률 기반 거짓 성공 차단). 근거·실측은 `docs/r6-contract.md`. 종료 조건은 `rate_http_only` 무회귀 + 동결 인수 green + codex 리뷰 open C/H 0 |

R1 종료 조건은 **보고서 1장**이다: "실제 리서치 실패율 Z%, Tier-1 돌파율 X%(3회 중앙값), 벤더별 분해, 원본 대비 Y%".

R2 종료 조건은 **SC-8·SC-9 통과 + `rate_http_only`가 R1 대비 회귀하지 않음**이다. Phase 0이 돌파율을 올려도 HTTP 경로의 실력이 떨어지면 R2는 끝나지 않는다.

**R2에서 하지 않기로 확정한 것** — 아래 세 항목은 R1 측정 결과를 근거로 R2 범위에서 제외됐다. 근거는 `docs/r2-contract.md` §2·§5.

| 항목 | 제외 근거 (실측) |
|---|---|
| URL 변형 | 성공 표본 8곳의 `<link rel="amphtml">` 선언 **0건**, 차단 4곳 × 변형 3종 회피 **0/12**(`m.` 호스트는 4곳 전부 DNS 부재). 지문표의 미실행 `mobile` 선언도 함께 제거한다 (NG-10) |
| yt-dlp 라우팅 | A1 표본 70건 중 미디어 URL **0건**, 대상은 사실상 1개 사이트, 외부 바이너리 의존이 SC-7과 충돌. **R4 이후 재검토** |
| 격자 플래너 확장 | R1 격차 원인 중 플래너에서 온 것 **0건**. US-B-009·010 이후 남는 실패를 규명해 R3에서 결정한다 |

---

## Non-Goals

`overview.md`의 NG-1 부터 NG-13 까지를 그대로 승계한다. 각 항목의 **강제 수단**은 위 Constraints·AC에 배선되어 있으며,
강제 수단이 코드에 없는 항목은 Non-Goal로 인정하지 않는다.

| # | 하지 않는 것 | 이 SPEC에서의 강제 지점 |
|---|-------------|------------------------|
| NG-1 | 로그인 월 우회 | AC-B-003-1, 종료 코드 2, G-3 음성 케이스 |
| NG-2 | 페이월 우회 | AC-B-003-2 |
| NG-3 | CAPTCHA 자동 해결 | AC-B-008-3, 의존성 allowlist |
| NG-4 | 자격증명·쿠키·세션 수집이나 저장 | AC-B-006-3, Observation 화이트리스트, 보안 절 |
| NG-5 | 대량 크롤링 | **재귀 링크 추적 부재**(취득 본문에서 링크를 뽑아 큐에 넣는 코드가 존재하지 않는다) + 입력은 사용자가 명시한 유한 목록이거나 상한이 걸린 검색 후보 + 호스트 동시성 1 · `MIN_HOST_INTERVAL_S` 하한. R6 개정: "`fetch`는 단건만"은 `--batch`·`search` 와 충돌하므로 폐기했다 — 크롤러가 되지 않게 하는 **실질 방벽은 재귀 금지**이지 단건 제한이 아니다 |
| NG-6 | 프록시 로테이션 | 프록시 인터페이스 부재, 의존성 allowlist |
| NG-7 | 원본 엔진 코드 벤더링 | `seeded_from` 필드, ADR-003 |
| NG-8 | 배터리에 없는 사이트를 지원으로 표기 | 문서 린트 (사이트명 목록 금지) |
| NG-9 | 사이트별 예외 규칙 축적 | **지문표**(`profiles.yaml`)에는 `detectors[].pattern` 호스트 리터럴 금지 린트. **API 인덱스**(`api_index.yaml`)는 호스트를 적는 것이 존재 이유이므로 리터럴 금지 대신 AC-B-010-15(20 항목 상한 + `source`·`verified_at` 의무)와 AC-B-010-8~14(조립 규칙)로 증식을 막는다 |
| NG-10 | 실패를 조용히 넘기기 | 11종 닫힌 분류 + `attempts` 길이 1 이상 |
| NG-11 | 내부망·메타데이터 접근 | AC-B-003-4, AC-B-003-5, 보안 절 SSRF 차단 |
| NG-12 | 본문 재배포·장기 보관 | AC-B-001-4, 보안 절 본문 미보관 |
| NG-13 | 지속 신원 위장 / 행동 시뮬레이션 | 보안 절 브라우저 티어 규칙, ADR-006 A8 4항 |
