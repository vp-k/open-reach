#!/usr/bin/env bash
# US-B-012 — Phase 0 공개 플랫폼 어댑터 확장 (R5)
# AC-B-012-1 / -3 / -4 + AC-B-010-11(R5 개정: endpoints 쿼리 치환자) + AC-B-010-15(합산 상한)
#
# R5 가 여는 것은 단 하나다: **chain 없는 endpoints 템플릿의 쿼리 값 위치 치환자**.
# 이 항목의 치환 입력은 입력 URL 캡처 그룹뿐이라 "응답이 쿼리 구조를 바꾼다"는
# 원래 금지의 근거가 성립하지 않는다 (실측: Bluesky XRPC 는 쿼리 전용). 열지 않은
# 것 — chain 쿼리 치환자, 쿼리 값의 `&`·`=`, 상한·출처 의무 — 이 그대로 닫혀
# 있는지를 여기서 못 박는다. us-b-010 과 같은 이유로 음성 케이스는 픽스처의
# 경로별 요청 수(hits)로 "요청이 아예 없었다"까지 단언한다.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_lib.sh"

IDX="$WORK/idx-b012"
mkdir -p "$IDX"

NETLOC="${BASE#http://}"

write_index() {
  sed -e "s|__BASE__|$BASE|g" -e "s|__NETLOC__|$NETLOC|g" > "$IDX/$1"
}

reset_hits() {
  "$PY" - "$BASE" <<'PY' >/dev/null 2>&1 || true
import sys, urllib.request
urllib.request.urlopen(sys.argv[1] + "/_hits/reset", timeout=10).read()
PY
}

hits() { # hits <path> — 선행 슬래시를 떼고 넘긴다 (Git Bash MSYS 경로 변환 회피)
  "$PY" - "$BASE" "${1#/}" <<'PY'
import json, sys, urllib.request
try:
    raw = urllib.request.urlopen(sys.argv[1] + "/_hits", timeout=10).read()
    data = json.loads(raw.decode("utf-8"))
except Exception:
    print("__HITS_ERROR__")
    sys.exit(0)
prefix = "/" + sys.argv[2]
print(sum(v for k, v in data.items() if k.startswith(prefix)))
PY
}

assert_hits() { # assert_hits <path-prefix> <expected> <label>
  local actual
  actual="$(hits "$1")"
  if [ "$actual" != "$2" ]; then
    fail "$3 (path=$1 expected=$2 actual=$actual)"
  fi
}

# ── 인덱스 정의 ────────────────────────────────────────────────────────────

# 쿼리 캡처 라우팅 + endpoints 쿼리 치환자 — HN `/item?id=N` 표현형의 최소 재현.
# url_pattern 은 `경로?쿼리` 에 매치한다 (R5 개정: entry_for 매칭 대상 확장).
write_index qquery.yaml <<'YAML'
entries:
  - host: __NETLOC__
    url_pattern: '^/q/item\?id=(?P<id>[0-9]+)$'
    source: "https://example.invalid/api-docs"
    verified_at: "2026-09-02"
    response_kind: json
    content_pointer: "item.text"
    endpoints:
      - "__BASE__/api/qitem?id={id}"
YAML

# 캡처 패턴이 일부러 느슨하다(`[^/]+`). 패턴이 `&`·`=` 를 통과시켜도 치환 검사가
# 독립적으로 막아야 한다 — us-b-010 slashy 와 같은 이중 검사 원리.
write_index qquery-lax.yaml <<'YAML'
entries:
  - host: __NETLOC__
    url_pattern: '^/q/item\?id=(?P<id>[^/]+)$'
    source: "https://example.invalid/api-docs"
    verified_at: "2026-09-02"
    response_kind: json
    content_pointer: "item.text"
    endpoints:
      - "__BASE__/api/qitem?id={id}"
YAML

# chain 템플릿의 쿼리 치환자 — R5 개정 뒤에도 여전히 로드 실패여야 한다.
# chain 의 치환 입력에는 응답 유래 값이 섞이므로 원래 금지의 근거가 그대로 산다.
write_index chainquery.yaml <<'YAML'
entries:
  - host: __NETLOC__
    url_pattern: "^/api/origin/(?P<name>[a-z0-9]+)$"
    source: "https://example.invalid/api-docs"
    verified_at: "2026-09-02"
    response_kind: html
    chain:
      - request: "__BASE__/api/step1/ok"
        response_kind: json
        select: "crate.max_stable_version"
        value_pattern: '^[0-9]+\.[0-9]+\.[0-9]+$'
        bind: version
      - request: "__BASE__/api/step2/x?v={version}"
        response_kind: html
YAML

# 어댑터가 인증 요구 콘텐츠에 닿는 경우 — 돌파 없이 auth_wall 로 중단 (AC-B-012-3).
write_index auth401.yaml <<'YAML'
entries:
  - host: __NETLOC__
    url_pattern: "^/api/origin/(?P<name>[a-z0-9]+)$"
    source: "https://example.invalid/api-docs"
    verified_at: "2026-09-02"
    response_kind: json
    content_pointer: "item.text"
    endpoints:
      - "__BASE__/api/auth401"
YAML

# entries 20 + search 1 = 21 — 합산 상한 초과 (AC-B-010-15 R5 개정, AC-B-014-4).
# entries 만 세는 구현은 20 이하로 통과시킨다 — 이 케이스가 그 구멍을 막는다.
{
  echo "entries:"
  for i in $(seq 1 20); do
    printf '  - host: "h%s.invalid"\n' "$i"
    printf '    url_pattern: "^/a%s/(?P<name>[a-z]+)$"\n' "$i"
    printf '    source: "https://example.invalid/api-docs"\n'
    printf '    verified_at: "2026-09-02"\n'
    printf '    response_kind: html\n'
    printf '    endpoints:\n'
    printf '      - "__BASE__/api/step2/{name}"\n'
  done
  echo "search:"
  echo '  - host: "s.invalid"'
  echo '    url_pattern: "^/find"'
  echo '    source: "https://example.invalid/api-docs"'
  echo '    verified_at: "2026-09-02"'
} | write_index mixed-oversize.yaml

# ── AC-B-010-11 (R5 개정): endpoints 쿼리 치환자 양성 경로 ──────────────────

note "AC-B-010-11(R5): 쿼리 캡처 라우팅 + endpoints 쿼리 치환자로 구제 성공"
reset_hits
run_engine fetch --api-index "$IDX/qquery.yaml" "$BASE/q/item?id=45"
assert_code 0 "쿼리 위치 치환자 구제가 성공해야 한다"
assert_expr "d.get('ok')" "True" "쿼리 캡처 구제 실패"
assert_expr "d.get('final_route')" "phase0" "구제 성공인데 final_route 가 phase0 이 아니다"
# 치환된 값이 실제 요청 쿼리에 실렸는가 — 픽스처가 수신 쿼리를 본문에 되비춘다.
# hits 는 쿼리를 떼고 세므로 이 마커만이 "쿼리가 실제로 전달됐다"를 증명한다.
assert_stdout_has "RAWQ[id=45]" "치환된 쿼리 값이 실제 요청에 실리지 않았다"
assert_hits "/api/qitem" "1" "어댑터 엔드포인트는 정확히 1회 요청"

note "AC-B-010-11(R5): 쿼리 위치 값에 '&'·'=' → 거부, 어댑터 요청 없음"
reset_hits
run_engine fetch --api-index "$IDX/qquery-lax.yaml" "$BASE/q/item?id=45&x=1"
assert_expr "d.get('ok')" "False" "쿼리 구조를 바꾸는 값은 구제 실패여야 한다"
assert_hits "/api/qitem" "0" "AC-B-010-11(R5) 금지 문자가 든 값으로 어댑터 요청이 나감"

note "AC-B-010-11(R5): chain 템플릿의 쿼리 치환자 → 여전히 로드 실패, 요청 없음"
reset_hits
run_engine fetch --api-index "$IDX/chainquery.yaml" "$BASE/api/origin/ok"
assert_code 3 "chain 쿼리 치환자는 R5 뒤에도 로드 실패(종료 코드 3)"
assert_hits "/api/step1" "0" "AC-B-010-11(R5) 로드 실패 전에 chain 요청이 나감"

# ── AC-B-012-3: 어댑터의 인증 경계 ─────────────────────────────────────────

note "AC-B-012-3: 어댑터 엔드포인트가 401 → auth_wall, 종료 코드 2"
reset_hits
run_engine fetch --api-index "$IDX/auth401.yaml" "$BASE/api/origin/ok"
assert_code 2 "인증 요구는 경계 보고(종료 코드 2)"
assert_expr "d.get('failure_reason')" "auth_wall" "AC-B-012-3 인증 요구가 auth_wall 로 보고되지 않음"
assert_expr "d.get('ok')" "False" "auth_wall 인데 ok=true"
assert_hits "/api/auth401" "1" "어댑터는 1회 두드리고 물러난다 (재시도·우회 없음)"

# ── AC-B-010-15 (R5 개정) / AC-B-014-4: 합산 상한 ──────────────────────────

note "AC-B-010-15(R5): entries 20 + search 1 = 21 → 로드 실패, 요청 없음"
reset_hits
run_engine fetch --api-index "$IDX/mixed-oversize.yaml" "$BASE/api/origin/ok"
assert_code 3 "합산 20 초과는 로드 실패(종료 코드 3)"
assert_hits "/api/step" "0" "AC-B-010-15(R5) 합산 상한 초과 인덱스로 요청이 나감"

finish
