#!/usr/bin/env bash
# US-B-003 (R6 개정) — robots.txt 는 경계가 아니라 모드다
# AC-B-003-6
#
# 이 개정은 사용자 승인 아래 경계를 **완화**한 것이라, 여기서 지켜야 할 것은
# "열렸다"가 아니라 **정확히 그만큼만 열렸다**는 사실이다. 그래서 세 모드를
# 출력이 아니라 **요청 카운터**로 가른다: `off` 는 robots.txt 를 조회하지 않고,
# `enforce` 는 R5 까지의 동작을 그대로 복원하며, `advisory` 는 조회하되 막지 않는다.
# 약속은 "판정을 받아 놓고 무시한다"가 아니라 "조회하지 않는다"이므로, 히트 0 이
# 아니면 문서가 거짓말이 된다.
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

assert_hits_at_least() { # assert_hits_at_least <path-prefix> <min> <label>
  local actual
  actual="$(hits "$1")"
  case "$actual" in
    __HITS_ERROR__) fail "$3 (히트 조회 실패)" ; return ;;
  esac
  if [ "$actual" -lt "$2" ]; then
    fail "$3 (path=$1 expected>=$2 actual=$actual)"
  fi
}

# `/norobots/doc` 은 픽스처 robots.txt 가 Disallow 한 경로이며, 내용 자체는
# 정상 공개 문서다 — 세 모드가 같은 URL 에서 갈리도록 고른 유일한 변수다.
TARGET="$BASE/norobots/doc"

# ── 기본값 off: 조회하지 않는다 (요청 0건) ─────────────────────────────────

note "AC-B-003-6: 기본 모드 off — robots.txt 요청 0건, Disallow 경로도 취득"
reset_hits
run_engine fetch "$TARGET"
assert_code 0 "기본 모드에서 Disallow 경로 취득이 실패했다"
assert_expr "d.get('ok')" "True" "AC-B-003-6 기본 off 에서 취득 실패"
assert_expr "d.get('final_route')" "http" "기본 off 는 HTTP 티어에서 그대로 취득한다"
assert_hits "/robots.txt" "0" "AC-B-003-6 off 인데 robots.txt 를 조회했다 — 약속은 '조회하지 않는다'이다"

# ── enforce: R5 까지의 동작을 정확히 복원 ──────────────────────────────────

note "AC-B-003-6: --robots enforce — policy_blocked, 종료 코드 2, rule=robots"
reset_hits
run_engine fetch --robots enforce "$TARGET"
assert_code 2 "enforce 에서 Disallow 경로가 차단되지 않았다"
assert_expr "d.get('ok')" "False" "AC-B-003-6 enforce 복원 실패"
assert_expr "d.get('failure_reason')" "policy_blocked" "AC-B-003-6 enforce 차단 사유가 다르다"
assert_expr "d['attempts'][0]['route']" "policy" "차단은 정책 계층에서 기록되어야 한다"
assert_expr "d['attempts'][0]['rule']" "robots" "AC-B-003-6 차단 규칙 식별이 사라졌다"
assert_hits_at_least "/robots.txt" 1 "enforce 인데 robots.txt 를 조회하지 않았다"
assert_hits "/norobots" "0" "enforce 인데 Disallow 경로를 두드렸다"

note "AC-B-003-6: --respect-robots 는 enforce 의 별칭 — 결과가 동일해야 한다"
reset_hits
run_engine fetch --respect-robots "$TARGET"
assert_code 2 "--respect-robots 가 enforce 를 켜지 않았다"
assert_expr "d.get('failure_reason')" "policy_blocked" "AC-B-003-6 별칭이 다른 결과를 냈다"
assert_expr "d['attempts'][0]['rule']" "robots" "AC-B-003-6 별칭 경로에서 규칙 식별이 사라졌다"
assert_hits "/norobots" "0" "--respect-robots 인데 Disallow 경로를 두드렸다"

# ── advisory: 조회하되 차단하지 않고, 보고는 남긴다 ────────────────────────

note "AC-B-003-6: --robots advisory — 취득은 하되 stderr 로 보고"
reset_hits
run_engine fetch --robots advisory "$TARGET"
assert_code 0 "advisory 가 차단했다 — advisory 는 막지 않는다"
assert_expr "d.get('ok')" "True" "AC-B-003-6 advisory 에서 취득 실패"
assert_hits_at_least "/robots.txt" 1 "advisory 인데 robots.txt 를 조회하지 않았다"
case "${ENG_ERR:-}" in
  *"robots advisory"*) : ;;
  *) fail "AC-B-003-6 advisory 인데 보고가 없다 (조용한 무시 금지, NG-10)" ;;
esac

# ── 모호한 입력은 조용히 해석하지 않는다 ───────────────────────────────────

note "AC-B-003-6: --robots off --respect-robots — 요청 전 exit 4"
reset_hits
run_engine fetch --robots off --respect-robots "$TARGET"
assert_code 4 "서로 다른 것을 지시하는 두 플래그가 조용히 한쪽으로 해석됐다"
assert_hits "/norobots" "0" "AC-B-003-6 사용 오류 판정 전에 요청이 나갔다"
assert_hits "/robots.txt" "0" "AC-B-003-6 사용 오류 판정 전에 robots 조회가 나갔다"

note "AC-B-003-6: 모르는 모드는 거부된다 — 켠 줄 알고 꺼진 채로 돌지 않는다"
reset_hits
run_engine fetch --robots bogus "$TARGET"
if [ "$ENG_CODE" = "0" ]; then
  fail "AC-B-003-6 모르는 모드가 통과했다 (조용히 off 로 강등)"
fi
assert_hits "/norobots" "0" "모르는 모드 거부 전에 요청이 나갔다"

# ── 완화 범위 고정: SSRF 는 어느 모드에서도 빠지지 않는다 ──────────────────

note "AC-B-003-6 경계: off 에서도 사설 대역 리디렉트는 차단된다 (NG-11 불변)"
reset_hits
run_engine fetch "$BASE/redir/private"
assert_code 2 "off 에서 SSRF 가드가 함께 풀렸다"
assert_expr "d.get('failure_reason')" "policy_blocked" "AC-B-003-6 완화 범위가 robots 를 넘었다"

finish
