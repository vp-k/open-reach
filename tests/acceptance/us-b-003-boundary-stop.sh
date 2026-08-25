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

note "robots.txt Disallow 경로는 policy_blocked"
run_engine fetch "$BASE/norobots/doc"
assert_code 2 "robots 차단 종료 코드 2"
assert_expr "d.get('failure_reason')" "policy_blocked" "robots Disallow 차단"
assert_expr "(d.get('attempts') or [{}])[0].get('route')" "policy" "robots 차단은 policy 경로"

finish
