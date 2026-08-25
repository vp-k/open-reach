#!/usr/bin/env bash
# US-B-008 — 응답 진위 판별
# AC-B-008-1 / -2 / -3 (-4 는 us-b-004 의 배터리 대조에서 검증)
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_lib.sh"

STATE="$WORK/state-008"
rm -rf "$STATE"
mkdir -p "$STATE"
export OPENREACH_STATE_DIR="$STATE"

note "AC-B-008-1: 200 이지만 챌린지 페이지 → ok=false"
run_engine fetch "$BASE/waf/challenge"
assert_code 1 "200 챌린지 exit 1"
assert_expr "d.get('ok')" "False" "AC-B-008-1 ok=false"
assert_expr "d.get('failure_reason') in {'waf_challenge','validation_failed'}" "True" "AC-B-008-1 사유"
assert_expr "d.get('content_markdown') is None" "True" "AC-B-008-1 챌린지 본문을 반환하지 않음"

note "AC-B-008-2: 403 + 차단 배너 → waf_challenge"
run_engine fetch "$BASE/waf/challenge-403"
assert_code 1 "403 차단 exit 1"
assert_expr "d.get('failure_reason')" "waf_challenge" "403 차단 사유"

note "AC-B-008-2 반례: 403 이지만 정상 본문 → 성공 (상태 코드 단독 판정 금지)"
run_engine fetch "$BASE/waf/forbidden-but-real"
assert_code 0 "403 정상 본문 exit 0"
assert_expr "d.get('ok')" "True" "403 정상 본문 ok=true"
assert_stdout_has "OPENREACH-BODY-MARKER" "403 정상 본문 추출"

note "AC-B-008-3: CAPTCHA 감지 → 해결 시도 없이 즉시 중단"
run_engine fetch --max-attempts 6 "$BASE/waf/captcha"
assert_code 1 "CAPTCHA exit 1"
assert_expr "d.get('failure_reason')" "waf_challenge" "CAPTCHA 사유=waf_challenge"
assert_expr "len(d.get('attempts') or []) == 1" "True" "AC-B-008-3 판정 후 추가 시도 없음"
assert_stdout_lacks "captcha_solved" "AC-B-008-3 CAPTCHA 해결 필드 부재"
assert_stdout_lacks "solver" "AC-B-008-3 CAPTCHA solver 필드 부재"

note "챌린지 응답의 Set-Cookie 가 출력에 노출되지 않는다 (NG-4)"
assert_stdout_lacks "fixture_clearance" "챌린지 쿠키 미노출"

note "빈 본문(길이 0) → validation_failed"
run_engine fetch "$BASE/err/404"
assert_expr "d.get('failure_reason')" "not_found" "404는 not_found (validation_failed 아님)"

note "explain 은 네트워크 판정 없이 계획만 출력한다"
run_engine explain "$BASE/public/article"
assert_code 0 "explain exit 0"
assert_expr "len(d.get('plan') or []) >= 1" "True" "explain plan 1개 이상"
assert_expr "all(all(k in p for k in ('route','impersonate','url_variant','order')) for p in (d.get('plan') or []))" "True" "explain plan 필드 4종"

finish
