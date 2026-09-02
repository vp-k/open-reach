#!/usr/bin/env bash
# US-B-014 — 명시적 검색 URL 본문 인정 (R5)
# AC-B-014-1 / -2 / -3 / -4 (+ AC-B-008-1 예외 경계)
#
# 검색 결과 목록은 짧은 블록의 나열이라 nav_shell 로 걸러진다 — 그것이 기본이고
# 옳다. R5 예외는 "사용자가 검색 결과를 **받으려고** 검색 URL 을 준 경우"뿐이며,
# 완화 범위는 nav_shell 판정 면제 하나다. 이 테스트는 예외가 정확히 그 폭만큼만
# 열렸는지를 사방에서 조인다: 선언 없으면 원래대로 실패, 리디렉트 도착은 실패,
# 챌린지·길이 하한은 유지, 선언 자체는 출처 의무를 진다.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_lib.sh"

IDX="$WORK/idx-b014"
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

# 검색 선언이 있는 인덱스. entries 의 항목은 이 테스트의 어떤 입력에도 매치하지
# 않는 들러리다 — 로더의 최상위 entries 요건을 지키면서 phase0 구제가 판정에
# 끼어들지 않게 한다.
write_index searchidx.yaml <<'YAML'
entries:
  - host: __NETLOC__
    url_pattern: "^/api/origin/(?P<name>[a-z0-9]+)$"
    source: "https://example.invalid/api-docs"
    verified_at: "2026-09-02"
    response_kind: html
    endpoints:
      - "__BASE__/api/step2/{name}"
search:
  - host: __NETLOC__
    url_pattern: '^/search/(results|challenge)\?q=.+'
    source: "https://example.invalid/search-docs"
    verified_at: "2026-09-02"
YAML

# 같은 entries, 검색 선언만 없다 — 선언 유무가 판정을 가르는 유일한 변수가 된다.
write_index nosearch.yaml <<'YAML'
entries:
  - host: __NETLOC__
    url_pattern: "^/api/origin/(?P<name>[a-z0-9]+)$"
    source: "https://example.invalid/api-docs"
    verified_at: "2026-09-02"
    response_kind: html
    endpoints:
      - "__BASE__/api/step2/{name}"
YAML

# 선언의 verified_at 누락 — 선언도 출처 의무를 진다 (AC-B-014-4).
write_index searchnodate.yaml <<'YAML'
entries:
  - host: __NETLOC__
    url_pattern: "^/api/origin/(?P<name>[a-z0-9]+)$"
    source: "https://example.invalid/api-docs"
    verified_at: "2026-09-02"
    response_kind: html
    endpoints:
      - "__BASE__/api/step2/{name}"
search:
  - host: __NETLOC__
    url_pattern: '^/search/results\?q=.+'
    source: "https://example.invalid/search-docs"
YAML

# 선언의 source 누락 — 검증 가능한 출처 없는 선언은 로드 시점에 거부 (AC-B-014-4).
write_index searchnosource.yaml <<'YAML'
entries:
  - host: __NETLOC__
    url_pattern: "^/api/origin/(?P<name>[a-z0-9]+)$"
    source: "https://example.invalid/api-docs"
    verified_at: "2026-09-02"
    response_kind: html
    endpoints:
      - "__BASE__/api/step2/{name}"
search:
  - host: __NETLOC__
    url_pattern: '^/search/results\?q=.+'
    verified_at: "2026-09-02"
YAML

# ── AC-B-014-1: 선언된 검색 URL 은 결과 목록을 본문으로 인정 ────────────────

note "AC-B-014-1: 선언된 검색 URL → 결과 목록이 유효 본문 (ok=true)"
reset_hits
run_engine fetch --api-index "$IDX/searchidx.yaml" "$BASE/search/results?q=rust"
assert_code 0 "선언된 검색 URL 은 성공해야 한다"
assert_expr "d.get('ok')" "True" "AC-B-014-1 선언된 검색 결과가 본문으로 인정되지 않음"
assert_expr "d.get('final_route')" "http" "검색 결과는 HTTP 티어에서 그대로 취득된다"

note "AC-B-008-1 기본: 같은 URL, 선언 없는 인덱스 → validation_failed"
reset_hits
run_engine fetch --api-index "$IDX/nosearch.yaml" "$BASE/search/results?q=rust"
assert_code 1 "선언 없는 검색 페이지는 원래대로 실패"
assert_expr "d.get('ok')" "False" "선언 없이 검색 결과가 성공으로 계상됨"
assert_expr "d.get('failure_reason')" "validation_failed" "AC-B-008-1 우발 검색 페이지 판정이 무너짐"

# ── AC-B-014-2: 명시성은 입력 URL 로만 — 리디렉트 도착은 우발이다 ───────────

note "AC-B-014-2: 리디렉트로 선언된 검색 페이지에 도착 → 여전히 validation_failed"
reset_hits
run_engine fetch --api-index "$IDX/searchidx.yaml" "$BASE/redir/tosearch"
assert_code 1 "리디렉트 도착은 명시가 아니다"
assert_expr "d.get('ok')" "False" "AC-B-014-2 리디렉트 도착이 성공으로 계상됨"
assert_expr "d.get('failure_reason')" "validation_failed" "AC-B-014-2 응답 사후 재분류 금지가 무너짐"
# 리디렉트 자체는 정상 추종된다 — 도착까지 해 놓고도 판정이 버텨야 의미가 있다.
# HTTP 티어가 몇 번 시도하는지는 이 AC 의 관심사가 아니므로 1회 이상만 단언한다.
_arrived="$(hits "/search/results")"
case "$_arrived" in
  0|__HITS_ERROR__) fail "AC-B-014-2 전제: 리디렉트가 검색 페이지에 도착하지 않음 (hits=$_arrived)" ;;
esac

# ── AC-B-014-3: 검색 URL 이라는 사실이 챌린지 판별을 무력화하지 않는다 ──────

note "AC-B-014-3: 선언된 검색 URL 에 챌린지 응답 → waf_challenge"
reset_hits
run_engine fetch --api-index "$IDX/searchidx.yaml" "$BASE/search/challenge?q=x"
assert_expr "d.get('ok')" "False" "AC-B-014-3 챌린지가 성공으로 계상됨"
assert_expr "d.get('failure_reason')" "waf_challenge" "AC-B-014-3 챌린지 판별이 검색 예외에 눌림"

# ── AC-B-014-1 후단: 완화는 nav_shell 면제뿐 — 길이 하한은 유지 ─────────────

note "AC-B-014-1: 선언된 검색 URL 의 빈 결과(<200자) → validation_failed"
reset_hits
run_engine fetch --api-index "$IDX/searchidx.yaml" "$BASE/search/results?q=none"
assert_code 1 "빈 결과 페이지는 선언과 무관하게 실패"
assert_expr "d.get('ok')" "False" "AC-B-014-1 빈 결과가 성공으로 계상됨"
assert_expr "d.get('failure_reason')" "validation_failed" "AC-B-014-1 길이 하한이 검색 예외에 눌림"

# ── AC-B-014-4: 선언의 출처 의무 ────────────────────────────────────────────

note "AC-B-014-4: 선언 verified_at 누락 → 로드 실패, 요청 없음"
reset_hits
run_engine fetch --api-index "$IDX/searchnodate.yaml" "$BASE/search/results?q=rust"
assert_code 3 "확인일 없는 선언은 로드 실패(종료 코드 3)"
assert_hits "/search" "0" "AC-B-014-4 로드 실패 전에 요청이 나감"

note "AC-B-014-4: 선언 source 누락 → 로드 실패, 요청 없음"
reset_hits
run_engine fetch --api-index "$IDX/searchnosource.yaml" "$BASE/search/results?q=rust"
assert_code 3 "source 없는 선언은 로드 실패(종료 코드 3)"
assert_hits "/search" "0" "AC-B-014-4 로드 실패 전에 요청이 나감 (source)"

finish
