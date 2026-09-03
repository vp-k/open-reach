#!/usr/bin/env bash
# US-B-003 — 경계 도달 시 즉시 중단
# AC-B-003-1 / -2 / -3 / -4 / -5
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_lib.sh"

note "AC-B-003-1: 로그인월 → auth_wall, 판정 후 추가 시도 없음"
run_engine fetch --max-attempts 6 "$BASE/wall/login"
assert_code 2 "auth_wall 종료 코드 2 (AC-B-003-3)"
assert_expr "d.get('failure_reason')" "auth_wall" "auth_wall 사유"
# 경계 판정은 첫 응답에서 확정되므로 시도가 누적되지 않는다.
assert_expr "len(d.get('attempts') or [])" "1" "AC-B-003-1 판정 후 추가 시도 없음"
assert_expr "(d.get('attempts') or [{}])[-1].get('outcome')" "wall" "마지막 시도 outcome=wall"

note "AC-B-003-2: 페이월 → paywall, 추가 시도 없음"
run_engine fetch --max-attempts 6 "$BASE/wall/paywall"
assert_code 2 "paywall 종료 코드 2 (AC-B-003-3)"
assert_expr "d.get('failure_reason')" "paywall" "paywall 사유"
assert_expr "len(d.get('attempts') or [])" "1" "AC-B-003-2 판정 후 추가 시도 없음"

note "AC-B-003-4: 사설/루프백 주소 → 네트워크 요청 없이 policy_blocked"
run_engine fetch "http://127.0.0.1:1/x"
assert_code 2 "루프백 종료 코드 2"
assert_expr "d.get('failure_reason')" "policy_blocked" "루프백 policy_blocked"
assert_expr "(d.get('attempts') or [{}])[0].get('route')" "policy" "AC-B-002-4 attempts[0].route=policy"
assert_expr "(d.get('attempts') or [{}])[0].get('status') is None" "True" "네트워크 요청 없음 (status=null)"

run_engine fetch "http://10.0.0.1/x"
assert_expr "d.get('failure_reason')" "policy_blocked" "RFC1918 차단"

run_engine fetch "http://169.254.169.254/latest/meta-data/"
assert_code 2 "메타데이터 주소 종료 코드 2"
assert_expr "d.get('failure_reason')" "policy_blocked" "메타데이터 주소 차단"

note "AC-B-003-4: http/https 외 스킴 거부"
run_engine fetch "file:///etc/passwd"
assert_code 2 "file 스킴 종료 코드 2"
assert_expr "d.get('failure_reason')" "policy_blocked" "file 스킴 차단"

note "AC-B-003-5: 리디렉션 매 홉 재검사 — 공개 → 사설"
run_engine fetch "$BASE/redir/private"
assert_code 2 "리디렉션 차단 종료 코드 2"
assert_expr "d.get('failure_reason')" "policy_blocked" "리디렉션 홉 차단"

# ── AC-B-003-6: robots 는 경계가 아니라 모드다 (R6 개정, 사용자 승인 재동결) ──
#
# 개정 전 이 자리는 "robots Disallow → policy_blocked" 한 방향만 못 박았다. 기본값이
# 뒤집혔다고 그 단언을 지우면 enforce 경로가 인수 커버리지에서 통째로 사라져,
# `--respect-robots` 가 조용히 무의미해지는 변이가 살아남는다. 그래서 **양쪽을 다** 고정한다.
#
# 위 AC-B-003-4/-5 (SSRF) 는 이 개정과 무관하다 — robots 만 빠지고 사설 대역·홉 재검사는
# 어느 모드에서도 그대로다 (NG-11 은 개정 대상이 아니다). 그 증거는 바로 위 케이스들이다.

# 픽스처가 센 경로별 요청 수. 선행 슬래시를 떼고 넘긴다 — Git Bash(MSYS)는 `/robots.txt`
# 처럼 생긴 인자를 네이티브 프로그램에 넘길 때 경로로 **변환한다**. 그러면 접두가 영원히
# 맞지 않아 항상 0 이 나오고, 0 을 기대하는 단언이 실패할 수 없는 단언이 된다.
assert_hits() { # assert_hits <path-prefix> <expected> <label>
  local actual
  actual="$("$PY" - "$BASE" "${1#/}" <<'PY'
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
)"
  if [ "$actual" != "$2" ]; then
    fail "$3 (path=$1 expected=$2 actual=$actual)"
  fi
}

reset_hits() {
  "$PY" - "$BASE" <<'PY' >/dev/null 2>&1 || true
import sys, urllib.request
urllib.request.urlopen(sys.argv[1] + "/_hits/reset", timeout=10).read()
PY
}

note "AC-B-003-6: 기본 모드(off)는 robots.txt 를 조회하지 않고 Disallow 경로도 취득한다"
reset_hits
run_engine fetch "$BASE/norobots/doc"
assert_code 0 "robots Disallow 경로가 기본값에서 취득되지 않았다"
assert_expr "d.get('ok')" "True" "off 모드 취득 실패"
# "따르지 않는다"가 아니라 "조회하지 않는다"가 약속이다. 판정을 받아 놓고 버리는 변이는
# 동작이 같아서 결과만 보는 단언으로는 잡히지 않는다 — 요청이 이미 나갔고 상대 서버는
# 그것을 봤기 때문이다. 히트 수 0 이 그 변이를 죽인다.
assert_hits "/robots.txt" "0" "AC-B-003-6 off 인데 robots.txt 를 조회했다"

note "AC-B-003-6: --respect-robots 는 R5 까지의 차단을 정확히 복원한다"
reset_hits
run_engine fetch --respect-robots "$BASE/norobots/doc"
assert_code 2 "robots 차단 종료 코드 2"
assert_expr "d.get('failure_reason')" "policy_blocked" "robots Disallow 차단"
assert_expr "(d.get('attempts') or [{}])[0].get('route')" "policy" "robots 차단은 policy 경로"
assert_expr "(d.get('attempts') or [{}])[0].get('rule')" "robots" "차단 규칙이 robots 로 표기되지 않았다"
assert_hits "/robots.txt" "1" "enforce 인데 robots.txt 를 조회하지 않았다"
assert_hits "/norobots" "0" "enforce 인데 차단 대상 본문을 두드렸다"

note "AC-B-003-6: 두 플래그가 어긋나면 요청 전에 거절한다 (어느 한쪽으로 조용히 해석 금지)"
reset_hits
run_engine fetch --robots off --respect-robots "$BASE/norobots/doc"
assert_code 4 "모순된 robots 지정은 사용 오류(종료 코드 4)"
# 거절은 요청보다 **먼저** 일어나야 한다. 나중에 거절하면 이미 두드린 뒤다.
assert_hits "/norobots" "0" "AC-B-003-6 모순 입력인데 요청이 먼저 나갔다"
assert_hits "/robots.txt" "0" "AC-B-003-6 모순 입력인데 robots 를 먼저 조회했다"

finish
