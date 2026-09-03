#!/usr/bin/env bash
# US-B-015 — 자기선언 열린문 티어 (R6)
# AC-B-015-1 / -2 / -3 / -4 / -5 / -6
#
# 이 티어의 가장 그럴듯한 거짓말 둘을 정면으로 조인다.
#   ① "선언이 없어도 한번 두드려 보기" — R2 에서 0/12 로 폐기된 맹목 변형이다.
#      결과가 아니라 **회선을 쓴다는 것 자체**가 위반이라, 동작이 아니라 요청
#      카운터로 검증한다.
#   ② "피드를 받았으니 성공" — 같은 호스트의 다른 글을 돌려주고 성공이라 부르는 것.
# HTTP 티어 재시도는 이 US 의 관심사가 아니므로 --max-attempts 1 로 고정한다.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_lib.sh"

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

ALT_COUNT="sum(1 for a in d['attempts'] if a['route'] == 'alternate')"

# ── AC-B-015-2: 선언이 없으면 요청을 만들지 않는다 ─────────────────────────

note "AC-B-015-2: 선언 없는 셸 → 이 티어의 요청 0건"
reset_hits
run_engine fetch --max-attempts 1 "$BASE/alt/none"
assert_code 1 "선언이 없으면 이 티어는 아무것도 구제하지 못한다"
assert_expr "d.get('failure_reason')" "validation_failed" "AC-B-015-1 진입 조건(셸 신호)이 무너졌다"
assert_expr "$ALT_COUNT" "0" "AC-B-015-2 선언이 없는데 대체 표현을 두드렸다 (맹목 변형 부활)"
assert_hits "/alt/none" "1" "AC-B-015-2 원문 요청이 1건을 넘었다 (--max-attempts 1)"

# ── AC-B-015-6 + 예산: JSON-LD 는 요청 0건으로 이긴다 ──────────────────────

note "AC-B-015-6: JSON-LD articleBody → 요청 0건으로 성공, 이력에 남는다"
reset_hits
run_engine fetch --max-attempts 1 "$BASE/alt/jsonld"
assert_code 0 "페이지가 스스로 실어 둔 본문을 못 읽었다"
assert_expr "d.get('ok')" "True" "AC-B-015-6 JSON-LD 구제 실패"
assert_expr "d.get('final_route')" "alternate" "AC-B-015-6 final_route 가 alternate 가 아니다"
assert_expr "$ALT_COUNT" "1" "AC-B-015-6 어떤 선언을 따랐는지가 이력에서 사라졌다"
assert_expr "[a['url_variant'] for a in d['attempts'] if a['route'] == 'alternate'][0]" "json" \
  "AC-B-015-6 따라간 선언의 종류가 표기되지 않았다"
assert_stdout_has "OPENREACH-BODY-MARKER" "JSON-LD 본문이 결과에 실리지 않았다"
# 같은 페이지에 피드도 선언돼 있다. JSON-LD 가 이겼다면 그 피드는 끝까지 0회다 —
# 우선순위(싼 승리 먼저)와 예산이 함께 지켜졌다는 뜻이다 (AC-B-015-4).
assert_hits "/altdecoy" "0" "AC-B-015-4 이미 이겼는데 남은 선언을 두드렸다"

# ── AC-B-015-5: 선언을 따라간 결과도 판정을 그대로 통과해야 한다 ───────────

note "AC-B-015-5: 단일 항목 피드 → 성공, 피드 요청은 정확히 1건"
reset_hits
run_engine fetch --max-attempts 1 "$BASE/alt/feed"
assert_code 0 "선언된 피드에서 본문을 회수하지 못했다"
assert_expr "d.get('final_route')" "alternate" "AC-B-015-6 피드 구제의 경로 표기가 틀렸다"
assert_expr "[a['url_variant'] for a in d['attempts'] if a['route'] == 'alternate'][0]" "rss" \
  "AC-B-015-6 피드 선언이 rss 로 표기되지 않았다"
assert_hits "/alt/feed.xml" "1" "AC-B-015-4 피드를 예산 밖으로 두드렸다"

note "AC-B-015-5: 요청한 문서가 없는 피드 → 다른 글을 성공이라 부르지 않는다"
reset_hits
run_engine fetch --max-attempts 1 "$BASE/alt/mismatch"
assert_code 1 "피드에 없는 문서를 성공으로 계상했다"
assert_expr "d.get('ok')" "False" "AC-B-015-5 다른 글이 성공이 됐다"
assert_expr "[a['outcome'] for a in d['attempts'] if a['route'] == 'alternate'][0]" "mismatch" \
  "AC-B-015-5 불일치가 이력에 남지 않았다"

# ── AC-B-015-3: 선언되어 있다고 안전한 것이 아니다 ─────────────────────────

note "AC-B-015-3: 선언된 주소가 사설 대역 → policy_blocked (NG-11 재검사)"
reset_hits
run_engine fetch --max-attempts 1 "$BASE/alt/ssrf"
assert_code 2 "선언된 사설 대역 주소가 SSRF 가드를 통과했다"
assert_expr "d.get('failure_reason')" "policy_blocked" "AC-B-015-3 후보 재검사가 없다"
assert_expr "d['attempts'][-1]['route']" "policy" "차단은 정책 계층에서 기록되어야 한다"

# ── AC-B-015-1: 경계는 이 티어로 뒤집히지 않는다 ───────────────────────────

note "AC-B-015-1: 로그인월 → 이 티어가 뜨지 않는다 (NG-1 불변)"
reset_hits
run_engine fetch --max-attempts 1 "$BASE/wall/login"
assert_code 2 "로그인월이 경계로 처리되지 않았다"
assert_expr "d.get('failure_reason')" "auth_wall" "AC-B-015-1 경계 판정이 흔들렸다"
assert_expr "$ALT_COUNT" "0" "AC-B-015-1 경계에서 대체 표현을 두드렸다 — 그 시도가 곧 NG-1 위반이다"

finish
