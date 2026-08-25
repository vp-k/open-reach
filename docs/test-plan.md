# Test Plan — open-reach (R1)

> **이 문서의 목적**: `docs/SPEC.md`의 AC를 **어떤 층위에서, 어떤 데이터로, 무엇을 실패시켜서** 검증하는지 확정한다.
> 구현 Phase는 이 계획 밖의 테스트 전략을 임의로 채택하지 않는다.

**대상 범위**: R1 구현 계약 (`fetch` HTTP 경로 · `explain` · `baseline` · `bench` · `compare` · 정책 가드 · 검증기 · 사유 분류 · 관측 스키마 · 본문 추출)

---

## 1. 근본 제약: 네트워크에 의존하는 제품을 결정론적으로 검증하기

이 도구의 본질은 **통제할 수 없는 원격 서버**를 상대하는 것이다. 실제 WAF 사이트를 테스트에 넣으면 테스트가 네트워크 상태·상대방 정책 변경에 따라 무작위로 깨진다. 따라서 층위를 분리한다.

| 층위 | 무엇을 검증하나 | 네트워크 | 결정론 |
|------|----------------|---------|--------|
| **단위 테스트** | 순수 함수 — 판정·분류·정규화·스키마·계획 수립 | 없음 | 완전 결정론 |
| **인수 테스트 (동결)** | CLI 계약 — 종료 코드·JSON 형태·경계 즉시 중단 | **로컬 픽스처 서버**(테스트가 직접 기동·종료) | 완전 결정론 |
| **벤치 (측정)** | 실제 돌파율 — SC-1/SC-2/SC-6 | 실제 인터넷 | 비결정론, 3회 중앙값 + dead-band 3%p |

**핵심 규칙**: 인수 테스트는 실제 WAF 사이트를 **한 건도** 포함하지 않는다. 실제 세계 성능은 `bench`가 측정하고, 그 결과는 CI 통과 조건이 아니라 **보고 대상**이다.

---

## 2. 테스트 피라미드 배분

| 층위 | 목표 비중 | 실행 시간 상한 | 실행 시점 |
|------|----------|---------------|----------|
| 단위 | 70% | 10초 | 매 커밋 |
| 인수 (CLI + 픽스처 서버) | 25% | 90초 | 매 커밋, 동결 해시 검증 포함 |
| 벤치 (실제 네트워크) | 5% | 30분 | 라운드 종료 시 · 엔진 변경 시 |

> 통합 층을 별도로 두지 않는다. 이 제품에서 "통합"의 실질은 CLI 계약이며, 그것을 인수 층이 이미 프로세스 경계에서 검증한다. 층을 하나 더 만들면 같은 것을 두 번 검증하는 비용만 생긴다.

---

## 3. 픽스처 서버 설계 (인수 테스트의 토대)

`tests/acceptance/run.sh` 가 **자기가 직접 기동하고 종료하는** 로컬 HTTP 서버. 포트는 0번 바인딩으로 OS가 할당하고, 실제 포트를 자식 테스트에 `OPENREACH_FIXTURE_BASE` 환경변수로 전달한다.

| 경로 | 응답 | 검증 대상 |
|------|------|----------|
| `/public/article` | 200, 본문 1200자 + script·nav·footer 포함 HTML | AC-B-001-1~4 (본문 추출·잡음 제거) |
| `/wall/login` | 200, 로그인 폼 + sign in to continue | AC-B-003-1 (auth_wall 즉시 중단) |
| `/wall/paywall` | 200, 중략 마커 + isAccessibleForFree false JSON-LD | AC-B-003-2 |
| `/waf/challenge` | 200, 제목 Just a moment + 본문 300자 | AC-B-008-1~2 (200이지만 실패) |
| `/waf/challenge-403` | 403, 차단 배너 | AC-B-008-2 (상태 코드 단독 판정 금지) |
| `/err/404` | 404 | AC-B-002-3 (`not_found`) |
| `/err/500` | 500 | AC-B-002-3 (`server_error`) |
| `/err/429` | 429 + `Retry-After: 1` | 백오프 · `rate_limited` |
| `/redir/private` | 302 → `http://127.0.0.1:1/x` | AC-B-003-5 (매 홉 재검사) |
| `/redir/public` | 302 → `/public/article` | 정상 리디렉션 추종 |
| `/robots.txt` | `Disallow: /norobots/` | robots 차단 |
| `/norobots/doc` | 200, 정상 공개 문서 (robots 로만 차단됨) | robots Disallow → `policy_blocked` |
| `/waf/forbidden-but-real` | 403, 정상 본문 | AC-B-008-2 반례 (403이어도 본문이면 성공) |

**격리 규칙**: 픽스처 서버의 런타임 산출물(로그·PID·임시 관측 파일)은 `mktemp -d` 로 만든 **`tests/acceptance/` 밖** 디렉토리에 둔다. 인수 테스트 동결 해시가 실행 부산물 때문에 깨지지 않게 하기 위함이다.

---

## 4. AC → 테스트 매핑

| AC | 층위 | 테스트 파일 | 실패 조건 |
|----|------|------------|----------|
| AC-B-001-1~3 | 인수 | `us-b-001-public-fetch.sh` | exit 0 아님 · ok true 아님 · 본문 200자 미만 · 메타 필드 누락 |
| AC-B-001-4 | 인수 | `us-b-001-public-fetch.sh` | 실행 후 관측 로그에 본문 문자열이 등장 |
| AC-B-002-1~4 | 인수 | `us-b-002-failure-classification.sh` | 사유가 11종 밖 · attempts 빈 배열 · 404/5xx 오분류 |
| AC-B-003-1~3 | 인수 | `us-b-003-boundary-stop.sh` | 판정 후 attempts 증가 · 종료 코드 2 아님 |
| AC-B-003-4~5 | 인수 | `us-b-003-boundary-stop.sh` | 사설 IP · file 스킴 · 리디렉션 차단 실패 |
| AC-B-004-1~5 | 인수 | `us-b-004-bench-rate.sh` | `BENCH_RESULT` 부재 · 분해 3종 부재 · 거버넌스 미검출 |
| AC-B-005-1~3 | 인수 | `us-b-005-compare-evidence.sh` | 증적 6필드 미충족 · 파일 선점 시 덮어씀 |
| AC-B-006-1~5 | 인수 | `us-b-006-observation.sh` | 금지 헤더 기록 · 정규화 실패 · 경계 경로 학습 |
| AC-B-007-1~4 | 인수 | `us-b-007-refresh.sh` | diff 미출력 · `last_reviewed` 미갱신 · 관측 0건에서 파일 변경 |
| AC-B-008-1~4 | 인수 | `us-b-008-response-validation.sh` | 챌린지를 성공으로 판정 · CAPTCHA 해결 시도 |
| 순수 판정 로직 | 단위 | `tests/unit/test_validators.py` | 아래 5절 참조 |
| 정책 가드 | 단위 | `tests/unit/test_policy.py` | 아래 5절 참조 |
| 스키마 불변식 | 단위 | `tests/unit/test_models.py` | 아래 5절 참조 |

---

## 5. 단위 테스트 목록 (순수 함수만)

**설계 원칙**: 계측(네트워크·파일 I/O)과 판정(순수 함수)을 분리한다. 판정 함수는 **문자열·딕셔너리를 받아 판정을 반환**하며 소켓을 열지 않는다. design-polish v2.2.0에서 검증된 분리 패턴을 그대로 따른다.

| 모듈 | 함수 | 케이스 수 | 핵심 케이스 |
|------|------|----------|------------|
| `validators` | `classify_response()` | 14 | 200+본문 → success / 200+챌린지 제목 → challenge / 200+로그인폼 → wall / 403+짧은본문+차단어휘 → challenge / 403+정상본문 → success(오탐 방지) / 404 → not_found / 429 → rate_limited |
| `validators` | `detect_paywall()` | 6 | isAccessibleForFree false / 중략 마커 / 둘 다 없음 → 미검출 |
| `validators` | `match_expected()` | 8 | title_contains / body_contains / min_chars / normalized_hash 각각 + 조합 + 전부 null → 계약 위반 예외 |
| `policy` | `check_scheme()` | 6 | http/https 허용, file/ftp/data/gopher 거부 |
| `policy` | `check_address()` | 16 | RFC1918 3대역 · 루프백 v4/v6 · 링크로컬 v4/v6 · CGNAT · ULA · 메타데이터 주소 · 공개 주소 허용 |
| `policy` | `check_redirect_chain()` | 5 | 공개→공개 허용 / 공개→사설 차단 / 홉 5 초과 차단 |
| `waf_detector` | `detect()` | 12 | 벤더 9종 각 1건 + `unknown_challenge` + `none` + 신호 2개 이상 시 confidence 상승 |
| `models` | `FetchResult` 불변식 | 5 | ok=true+failure_reason → 예외 / ok=false+attempts 빈 배열 → 예외 |
| `models` | `Observation` 화이트리스트 | 6 | 8키 정상 / `set_cookie` 키 → `ObservationSchemaError` / `content` 키 → 예외 |
| `url_transforms` | `normalize()` | 8 | query·fragment·userinfo 제거 / 대문자 호스트 소문자화 / 기본 포트 제거 |
| `planner` | `build_plan()` | 7 | 관측 있으면 직전 성공 경로가 첫 원소 / 경계 위반 관측은 무시 / `max_attempts` 상한 준수 |
| `bench.compare` | `classify_regression()` | 6 | dead-band 3%p 안 → none / 밖 하락 → regressed / battery_hash 불일치 → incomparable |
| `bench.governance` | `check_battery()` | 8 | G-1 벤더 2개 미만 / G-3 음성 케이스 0건 / G-4 필드 누락 / G-6 항목 50 초과 / 정상 통과 |

**합계 목표**: 107건 이상.

---

## 6. 실패 경로 우선 (Failure-path first)

이 제품에서 **정상 경로는 소수이고 실패 경로가 다수**다. 따라서 테스트 작성 순서를 뒤집는다.

1. 경계 판정 (wall / paywall / policy) — 여기서 틀리면 제품의 존재 이유가 무너진다
2. 실패 분류 (11종 닫힌 집합) — 여기서 틀리면 사용자가 다음 행동을 못 정한다
3. 응답 진위 판별 — 여기서 틀리면 돌파율 수치 전체가 거짓이 된다
4. 정상 본문 추출 — 위 셋이 맞은 뒤에야 의미가 있다

---

## 7. 엣지 케이스 목록

| # | 케이스 | 기대 동작 |
|---|--------|----------|
| E-1 | 200이지만 본문 0바이트 | `validation_failed` |
| E-2 | `Content-Type: application/pdf` | `unsupported` (본문 추출 대상 아님) |
| E-3 | 응답 본문 50MB | 스트리밍 상한(10MB)에서 절단 후 `validation_failed` |
| E-4 | 리디렉션 루프 (A→B→A) | 홉 상한에서 `policy_blocked` |
| E-5 | DNS가 사설 IP와 공개 IP를 함께 반환 | **차단** (모든 레코드 검사, 하나라도 사설이면 거부) |
| E-6 | `Retry-After`가 초 단위가 아닌 HTTP-date 형식 | 파싱해 대기, 파싱 실패 시 지수 백오프 |
| E-7 | 관측 파일이 손상된 JSON 줄 포함 | 해당 줄만 건너뛰고 경고, 전체 실패 아님 |
| E-8 | `profiles.yaml` 쓰기 중 프로세스 종료 | rename 전이므로 원본 무손상 |
| E-9 | 동일 호스트 동시 요청 2건 | 직렬화(동시성 1), 최소 간격 준수 |
| E-10 | 배터리에 중복 `id` | 거버넌스 사전 검사에서 exit 3 |
| E-11 | UTF-8 아닌 인코딩(EUC-KR) 응답 | 선언된 charset 존중해 디코딩, 실패 시 `validation_failed` |
| E-12 | `Content-Encoding: br` | 해제 후 판정 |

---

## 8. 테스트 데이터 설계

- **픽스처 HTML은 실제 사이트의 복사본이 아니다.** 각 판정 신호(챌린지 제목·로그인 폼·중략 마커)를 **최소 재현 형태**로 직접 작성한다. 실제 사이트 HTML을 저장소에 넣으면 NG-12(본문 재배포 금지)를 스스로 위반한다.
- **배터리 픽스처**(`bench` 테스트용)는 픽스처 서버 URL만 사용하는 별도 파일 `tests/fixtures/battery-local.yaml` 로 두고 `bench --battery <경로>` 로 지정한다. 실제 배터리 `bench/battery.yaml` 은 인수 테스트에서 읽지 않는다.
- 픽스처 배터리는 헤더에 `role: fixture` 를 선언한다. 벤더 커버리지(G-1)는 출하 배터리의 요건이므로 fixture 에는 적용되지 않으며, 반대로 출하 배터리를 `fixture` 로 강등해 G-1을 피하는 경로는 exit 4로 막힌다.
- 배터리 URL은 실행 시점에 결정되는 포트를 포함하므로, 픽스처 파일은 `__FIXTURE_BASE__` 자리표시자를 쓰고 테스트가 `$OPENREACH_WORK_DIR` 에 치환본을 만들어 사용한다.
- 거버넌스 위반 배터리 4종(G-1/G-3/G-4/G-6 위반)을 각각 별도 픽스처로 준비한다.

---

## 9. 계약 테스트 (Contract tests)

외부 시스템과의 계약은 두 개뿐이다.

| 계약 상대 | 계약 내용 | 검증 방법 |
|-----------|----------|----------|
| `curl_cffi` | `impersonate` 인자로 TLS 지문을 선택할 수 있고, 지원 후보 목록을 조회할 수 있다 | 설치 시점 스모크: 후보 목록이 비어있지 않고 `profiles.yaml`의 모든 후보가 그 목록에 존재 |
| 원본 insane-search | `compare`가 호출하는 실행 인터페이스 | 미설치·오류 시 `unmeasurable`로 정상 종료 (계약 부재를 실패로 만들지 않는다) |

---

## 10. 동결 인수 테스트 규약 (auto-complete-loop)

- `tests/acceptance/run.sh` 는 마지막 줄에 `ACCEPTANCE_RESULT: total=N passed=N failed=N` 을 출력한다.
- 종료 코드 0은 total 1 이상 AND failed 0 일 때만이다.
- 각 User Story 테스트는 `us-<id>-<slug>.sh` 형식이며 실행 권한을 갖는다.
- **Phase 1 종료 시점에는 전부 red 여야 한다** — 엔진이 없으므로 실패하는 것이 정상이고, 실패가 아니라 통과하면 그 테스트는 아무것도 검증하지 않는 스텁이다.
- 동결 이후 구현 Phase는 이 파일들을 수정할 수 없다. 스펙 변경이 필요하면 사용자 승인 후 재동결한다.

---

## 11. 이 계획이 검증하지 않는 것

| 검증하지 않는 것 | 이유 | 대신 무엇이 담당하나 |
|-----------------|------|---------------------|
| 실제 WAF 사이트 돌파 여부 | 비결정론적이고 상대방 정책에 종속 | `bench` 측정 (CI 게이트 아님) |
| 브라우저 티어 동작 | R3 범위이며 A8 심사 통과가 선행 조건 | R3 테스트 계획에서 확정 |
| 성능 벤치마크(처리량) | 단건 조회 도구이고 처리량이 목표가 아님 | Constraints의 벽시계 상한만 인수 테스트에서 확인 |
| 마켓플레이스 설치 경험 | R3/R4 범위 | SC-7 설치 시험 |

---

## 변경 이력

| 날짜 | 변경 | 사유 |
|------|------|------|
| 2026-08-25 | 최초 작성 (피라미드 배분, 픽스처 서버, AC 매핑, 단위 107건, 엣지 12종) | Phase 1 문서 기획 |
