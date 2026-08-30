# 외부 검토 기록 — 코드 리뷰 라운드 10 (codex)

- 일시: 2026-08-28
- 검토자: codex (sandbox=read-only, 파일 미변경)
- 대상: `transport.py` 임퍼소네이션 경로 복구 + `fetcher.py` 차단 사유 관측 + `policy.py` IPv6 언랩 (`r10.diff`, 287줄)
- 결과: **CRITICAL 1 / MAJOR 1 / MINOR 1** — 전부 반영

이 라운드는 **정적 검토가 9라운드 동안 찾지 못한 것을 실행이 찾아낸** 뒤에 열렸다.
`curl_cffi` 를 설치하자 인수 스위트가 8/8 → 1/8 로 떨어졌고, 원인은 존재하지 않는
`resolve=` 요청 인자였다. 즉 제품의 주 경로가 이 환경에서 **한 번도 성공적으로
실행된 적이 없었다**. 라운드 10은 그 복구본을 대상으로 한다.

## 지적과 반영

| # | 심각도 | 지적 | 반영 |
|---|--------|------|------|
| 1 | **CRITICAL** | `trust_env=False` 는 설치본(0.16.2)이 속성으로 **저장만** 하고 프록시 적용에 쓰지 않는다. libcurl 이 스스로 `http_proxy`/`ALL_PROXY` 를 읽으므로 환경 프록시가 그대로 살아 있고, 프록시를 타면 대상 이름을 프록시가 해석해 `CURLOPT_RESOLVE` 고정이 무효화되며 `primary_ip` 는 프록시 주소라 사후 확인마저 대상이 아닌 것을 확인한다 — **SSRF 방어 두 겹이 동시에 붕괴** | `_connection_options()` 신설. 프록시 차단을 인자가 아닌 **핸들 옵션**(`CURLOPT_PROXY=""` + `CURLOPT_NOPROXY="*"`)으로 옮기고, 능력 검사와 실제 요청이 **같은 옵션 묶음**을 쓰게 통합 |
| 2 | **MAJOR** | `_embedded_v4` 가 NAT64 변환 주소를 놓친다. `64:ff9b::a9fe:a9fe`(169.254.169.254)·`64:ff9b::7f00:1`(127.0.0.1)·RFC 8215 `64:ff9b:1::/48` 이 모두 통과 | `_nat64_embedded()` + `_rfc6052_extract()` 신설. RFC 6052 well-known `/96` 과 RFC 8215 local-use `/48`(배치 96/64/56/48 전부)을 풀어 대조. u 옥텟(비트 64..71)은 건너뛴다 |
| 3 | MINOR | `_UNPROBED` 캐시와 1회성 경고가 스레드 안전하지 않다 | `_probe_lock` 도입. 판정은 double-checked locking, 경고 플래그는 락 안에서 갱신 |

## 검토자가 명시적으로 통과시킨 항목

- `CURLOPT_RESOLVE` slist 가 리디렉션 홉 사이로 새지 않음 — 홉마다 새 `Session` 을 만들고 닫기 때문
- `no_impersonate` 계획 평탄화가 시도 예산·순서를 깨지 않음
- `_explain_block` 이 URL 질의·경로 토큰을 stderr 로 흘리지 않음

## 회귀 테스트 (검토자가 요구한 형태 그대로)

`tests/unit/` 신설 — `docs/test-plan.md` 5절이 지정한 자리다.

| 파일 | 검증 |
|------|------|
| `test_transport_proxy.py` | `http_proxy`/`https_proxy`/`ALL_PROXY` 를 모두 설정한 뒤 요청 → 가짜 프록시가 연결을 **0건** 받는다 |
| `test_policy_nat64.py` | `64:ff9b::a9fe:a9fe` · `64:ff9b::7f00:1` · `64:ff9b:1::7f00:1` 등 5종이 `private_range` 로 차단되고, 사유 문장이 **실제 목적지 IPv4** 를 지목한다. 공인 IPv4 를 담은 `64:ff9b::808:808` 은 통과 |

**테스트가 실제로 버그를 잡는지 확인함**: 수정 전 조합(`trust_env=False` 만)으로 같은
시나리오를 돌리면 프록시가 연결을 **1건** 받는다. 수정 후 0건.

## 결과

- `tests/unit`: 9 passed
- 동결 인수 스위트: `ACCEPTANCE_RESULT: total=8 passed=8 failed=0` (수정 후 재확인)
- `tests/lib-smoke.sh`: PASS

## 부수 개선

NAT64 `/48` 배치 후보 순서를 `(96, 64, 56, 48)` 로 두었다. 차단은 어느 순서든
되지만, 사유 문장은 **처음 걸린 배치**를 인용하므로 순서가 뒤집히면
`64:ff9b:1::7f00:1` 을 막고도 사유에 `127.0.0.1` 대신 다른 배치의 부산물인
`0.0.0.0` 이 찍혀 진단이 사람을 헷갈리게 한다. 회귀 테스트가 이 문장까지 검사한다.
