#!/usr/bin/env bash
# US-B-010 — Phase 0 공개 API 라우팅: 조립 규칙 음성 케이스
# AC-B-010-8 / -9 / -10 / -11 / -12 / -13 / -14
#
# 왜 음성만 모았나.
#   2-hop 은 **상대 서버의 응답이 우리 다음 요청 URL 에 영향을 주는** 첫 경로다.
#   리디렉션이 아니라 우리가 자발적으로 조립하는 URL 이라 hop_guard 가 보지 않는다.
#   "가드가 있다"는 코드를 읽어서 확신할 수 있는 종류가 아니므로, 가드가 **작동하지
#   않으면 실패하는** 케이스로 고정한다. 양성 경로(정상 구제)는 US-B-010 양성 테스트가
#   따로 맡는다.
#
# "요청하지 않았다"는 출력만으로는 요청이 없었는지 있었다가 실패했는지 구분되지
# 않는다. 픽스처 서버가 경로별 요청 수를 직접 세고, 여기서 그 수를 단언한다.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_lib.sh"

IDX="$WORK/idx"
mkdir -p "$IDX"

# BASE = http://127.0.0.1:PORT — 인덱스의 host 는 netloc(호스트:포트)로 대조한다
NETLOC="${BASE#http://}"

# write_index <파일명> — stdin 의 YAML 에서 __BASE__/__NETLOC__ 을 치환해 저장한다.
# 따옴표 heredoc 으로 받으므로 value_pattern 의 역슬래시가 셸에 먹히지 않는다.
write_index() {
  sed -e "s|__BASE__|$BASE|g" -e "s|__NETLOC__|$NETLOC|g" > "$IDX/$1"
}

reset_hits() {
  "$PY" - "$BASE" <<'PY' >/dev/null 2>&1 || true
import sys, urllib.request
urllib.request.urlopen(sys.argv[1] + "/_hits/reset", timeout=10).read()
PY
}

hits() { # hits <path> — 픽스처가 센 해당 경로 요청 수 (접두 일치)
  "$PY" - "$BASE" "$1" <<'PY'
import json, sys, urllib.request
try:
    raw = urllib.request.urlopen(sys.argv[1] + "/_hits", timeout=10).read()
    data = json.loads(raw.decode("utf-8"))
except Exception:
    print("__HITS_ERROR__")
    sys.exit(0)
prefix = sys.argv[2]
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

# 모든 step1 응답에는 next_url=/api/evil 이 심어져 있다. 응답이 지시한 목적지를
# 따라가면 이 경로에 요청이 남는다 — 어느 케이스에서도 0이어야 한다.
assert_no_evil() { assert_hits "/api/evil" "0" "AC-B-010-12 응답이 지시한 목적지를 따라감 ($1)"; }

# ── 인덱스 정의 ────────────────────────────────────────────────────────────

write_index chain3.yaml <<'YAML'
entries:
  - host: __NETLOC__
    url_pattern: "^/api/origin/(?P<name>[a-z0-9]+)$"
    source: "https://example.invalid/api-docs"
    verified_at: "2026-08-30"
    response_kind: html
    chain:
      - request: "__BASE__/api/step1/ok"
        response_kind: json
        select: "crate.max_stable_version"
        value_pattern: '^[0-9]+\.[0-9]+\.[0-9]+$'
        bind: version
      - request: "__BASE__/api/step1/ok"
        response_kind: json
        select: "crate.max_stable_version"
        value_pattern: '^[0-9]+\.[0-9]+\.[0-9]+$'
        bind: version2
      - request: "__BASE__/api/step2/{version2}"
        response_kind: html
YAML

write_index nopattern.yaml <<'YAML'
entries:
  - host: __NETLOC__
    url_pattern: "^/api/origin/(?P<name>[a-z0-9]+)$"
    source: "https://example.invalid/api-docs"
    verified_at: "2026-08-30"
    response_kind: html
    chain:
      - request: "__BASE__/api/step1/ok"
        response_kind: json
        select: "crate.max_stable_version"
        bind: version
      - request: "__BASE__/api/step2/{version}"
        response_kind: html
YAML

write_index hostbind.yaml <<'YAML'
entries:
  - host: __NETLOC__
    url_pattern: "^/api/origin/(?P<name>[a-z0-9]+)$"
    source: "https://example.invalid/api-docs"
    verified_at: "2026-08-30"
    response_kind: html
    chain:
      - request: "__BASE__/api/step1/ok"
        response_kind: json
        select: "host"
        value_pattern: '^[a-z.]+$'
        bind: apihost
      - request: "http://{apihost}/api/step2/x"
        response_kind: html
YAML

# 변종 인덱스 — step1 만 바꿔 가며 조립 규칙 하나씩을 겨눈다
for variant in array mismatch slashy; do
  write_index "step1-$variant.yaml" <<YAML
entries:
  - host: __NETLOC__
    url_pattern: "^/api/origin/(?P<name>[a-z0-9]+)\$"
    source: "https://example.invalid/api-docs"
    verified_at: "2026-08-30"
    response_kind: html
    chain:
      - request: "__BASE__/api/step1/$variant"
        response_kind: json
        select: "crate.max_stable_version"
        value_pattern: '^[0-9A-Za-z._/-]+\$'
        bind: version
      - request: "__BASE__/api/step2/{version}"
        response_kind: html
YAML
done

write_index norobots.yaml <<'YAML'
entries:
  - host: __NETLOC__
    url_pattern: "^/api/origin/(?P<name>[a-z0-9]+)$"
    source: "https://example.invalid/api-docs"
    verified_at: "2026-08-30"
    response_kind: html
    chain:
      - request: "__BASE__/api/step1/norobots"
        response_kind: json
        select: "crate.max_stable_version"
        value_pattern: '^[a-z]+$'
        bind: seg
      - request: "__BASE__/norobots/{seg}"
        response_kind: html
YAML

write_index budget.yaml <<'YAML'
entries:
  - host: __NETLOC__
    url_pattern: "^/api/origin/(?P<name>[a-z0-9]+)$"
    source: "https://example.invalid/api-docs"
    verified_at: "2026-08-30"
    response_kind: json
    content_pointer: "body"
    endpoints:
      - "__BASE__/api/ep1"
      - "__BASE__/api/ep2"
      - "__BASE__/api/ep3"
      - "__BASE__/api/ep4"
YAML

# ── 로드 시점에 거부되어야 하는 것 (네트워크 요청 0건) ──────────────────────

note "AC-B-010-8: chain 3단 → 로드 실패, 요청 없음"
reset_hits
run_engine fetch --api-index "$IDX/chain3.yaml" "$BASE/api/origin/ok"
assert_code 3 "chain 길이 3은 로드 실패(종료 코드 3)"
assert_hits "/api/step1" "0" "AC-B-010-8 로드 실패 전에 요청이 나감"
assert_no_evil "chain3"

note "AC-B-010-10: value_pattern 누락 → 로드 실패, 요청 없음"
reset_hits
run_engine fetch --api-index "$IDX/nopattern.yaml" "$BASE/api/origin/ok"
assert_code 3 "value_pattern 없는 항목은 로드 실패(종료 코드 3)"
assert_hits "/api/step1" "0" "AC-B-010-10 패턴 없이 요청이 나감"

note "AC-B-010-12: 호스트를 응답 값으로 바인딩 → 로드 실패"
reset_hits
run_engine fetch --api-index "$IDX/hostbind.yaml" "$BASE/api/origin/ok"
assert_code 3 "스킴·호스트는 템플릿 고정 — bind 는 로드 실패(종료 코드 3)"
assert_hits "/api/step1" "0" "AC-B-010-12 호스트 바인딩 인덱스로 요청이 나감"

# ── 1단은 정상이나 2단으로 넘어가면 안 되는 것 ──────────────────────────────

note "AC-B-010-9: select 가 배열 → 2단 요청 없음"
reset_hits
run_engine fetch --api-index "$IDX/step1-array.yaml" "$BASE/api/origin/ok"
assert_expr "d.get('ok')" "False" "배열 바인딩은 구제 실패여야 한다"
assert_hits "/api/step1" "1" "1단은 1회만 요청"
assert_hits "/api/step2" "0" "AC-B-010-9 스칼라가 아닌데 2단 요청이 나감"
assert_no_evil "array"

note "AC-B-010-10: value_pattern 불일치 → 2단 요청 없음"
reset_hits
run_engine fetch --api-index "$IDX/step1-mismatch.yaml" "$BASE/api/origin/ok"
assert_expr "d.get('ok')" "False" "패턴 불일치는 구제 실패여야 한다"
assert_hits "/api/step2" "0" "AC-B-010-10 패턴 불일치인데 2단 요청이 나감"
assert_no_evil "mismatch"

note "AC-B-010-11: 값에 경로 구분자 → 세그먼트 이탈 거부, 2단 요청 없음"
# 이 인덱스의 value_pattern 은 일부러 슬래시를 허용한다. 패턴이 느슨해도
# 세그먼트 검사가 독립적으로 막아야 한다 (이중 검사).
reset_hits
run_engine fetch --api-index "$IDX/step1-slashy.yaml" "$BASE/api/origin/ok"
assert_expr "d.get('ok')" "False" "세그먼트 이탈 값은 구제 실패여야 한다"
assert_hits "/api/step2" "0" "AC-B-010-11 세그먼트 이탈 값으로 2단 요청이 나감"
assert_hits "/norobots" "0" "AC-B-010-11 경로 탈출이 성립했다"
assert_no_evil "slashy"

# ── 조립은 성립하나 정책이 막아야 하는 것 ───────────────────────────────────

note "AC-B-010-13: 조립된 URL 이 robots Disallow → policy_blocked"
reset_hits
run_engine fetch --api-index "$IDX/norobots.yaml" "$BASE/api/origin/ok"
assert_code 2 "조립 URL 의 정책 차단은 종료 코드 2"
assert_expr "d.get('failure_reason')" "policy_blocked" "AC-B-010-13 조립 URL robots 재검사"
assert_hits "/norobots" "0" "AC-B-010-13 robots 재검사 없이 요청이 나감"
assert_no_evil "norobots"

# ── 예산 ────────────────────────────────────────────────────────────────────

note "AC-B-010-14: 항목당 요청 예산 3회 — 4번째 엔드포인트는 요청되지 않음"
reset_hits
run_engine fetch --api-index "$IDX/budget.yaml" "$BASE/api/origin/ok"
assert_expr "d.get('ok')" "False" "본문 없는 엔드포인트만으로는 구제 실패"
assert_hits "/api/ep4" "0" "AC-B-010-14 예산 3회를 넘겨 4번째가 요청됨"
assert_no_evil "budget"

finish
