#!/usr/bin/env bash
# US-B-002 — 분류된 실패 보고
# AC-B-002-1 / -2 / -3 / -4
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_lib.sh"

REASONS="{'auth_wall','paywall','policy_blocked','waf_challenge','rate_limited','not_found','server_error','network','validation_failed','unsupported','unknown'}"

check_failure() { # check_failure <url> <expected_reason> <expected_code> <label>
  run_engine fetch "$1"
  assert_code "$3" "$4 종료 코드"
  assert_expr "d.get('ok')" "False" "$4 ok=false"
  assert_expr "d.get('failure_reason') in $REASONS" "True" "$4 사유가 11종 안 (AC-B-002-1)"
  assert_expr "d.get('failure_reason')" "$2" "$4 사유=$2"
  assert_expr "len(d.get('attempts') or []) >= 1" "True" "$4 attempts 비어있지 않음 (AC-B-002-4)"
  assert_expr "all(all(k in a for k in ('route','impersonate','url_variant','status','elapsed_ms','outcome')) for a in (d.get('attempts') or []))" "True" "$4 attempts 필드 6종 (AC-B-002-2)"
}

note "AC-B-002-3: 404 → not_found"
check_failure "$BASE/err/404" "not_found" 1 "404"

note "AC-B-002-3: 5xx → server_error"
check_failure "$BASE/err/500" "server_error" 1 "500"

note "AC-B-002-3: DNS 실패 → network"
check_failure "http://open-reach-does-not-exist.invalid/x" "network" 1 "DNS 실패"

note "429 → rate_limited, 재시도 총량이 max_attempts 이하"
run_engine fetch --max-attempts 3 "$BASE/err/429"
assert_code 1 "429 종료 코드"
assert_expr "d.get('failure_reason')" "rate_limited" "429 사유"
assert_expr "len(d.get('attempts') or []) <= 3" "True" "재시도 총량 상한 준수"

note "AC-B-002-2: attempts 순서가 시도 순서와 일치 (elapsed_ms 존재)"
assert_expr "all(isinstance(a.get('elapsed_ms'), int) and a['elapsed_ms'] >= 0 for a in (d.get('attempts') or []))" "True" "elapsed_ms 정수"

finish
