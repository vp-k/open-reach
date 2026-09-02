#!/usr/bin/env bash
# US-B-011 — 브라우저 티어 (T2, R3)
#   allow_browser 일 때만, 그리고 HTTP·Phase 0 가 waf_challenge/js_shell 로 막힌 뒤에만
#   실제 브라우저로 렌더해 공개 본문을 취득한다. 브라우저가 미설치면 없는 돌파를 지어내지
#   않고 browser_disabled 정책 사유로 강등한다(SC-7: T1 경로 설치 0). 챌린지를 '해결'하지
#   않는다(NG-3) — 스스로 풀리는 렌더만 넘는다.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_lib.sh"

JS_URL="$BASE/waf/js-challenge"

note "--allow-browser 없이: JS 챌린지는 HTTP 티어에서 waf_challenge 로 막힌다"
run_engine fetch "$JS_URL"
assert_code 1 "브라우저 없이 종료 코드 1 (waf_challenge 는 경계 아님)"
assert_expr "d.get('ok')" "False" "브라우저 없이 실패"
assert_expr "d.get('failure_reason')" "waf_challenge" "HTTP 티어 판정 = waf_challenge"
assert_expr "all(a.get('route') != 'browser' for a in (d.get('attempts') or []))" "True" \
  "브라우저 티어 미개입 (--allow-browser 없이는 오르지 않는다)"

note "경계(로그인월)는 --allow-browser 여도 브라우저로 넘기지 않는다 (NG-1)"
run_engine fetch --allow-browser "$BASE/wall/login"
assert_code 2 "로그인월 종료 코드 2 (경계)"
assert_expr "d.get('failure_reason')" "auth_wall" "로그인월 = auth_wall"
assert_expr "all(a.get('route') != 'browser' for a in (d.get('attempts') or []))" "True" \
  "경계에서 브라우저 티어 미개입 (auth_wall 은 렌더 대상 아님)"

if "$PY" -c "from open_reach.browser import browser_available; import sys; sys.exit(0 if browser_available()[0] else 1)" 2>/dev/null; then
  note "브라우저 설치됨: --allow-browser 로 JS 챌린지를 렌더 돌파한다"
  run_engine fetch --allow-browser "$JS_URL"
  assert_code 0 "브라우저 돌파 종료 코드 0"
  assert_expr "d.get('ok')" "True" "브라우저 돌파 성공"
  assert_expr "d.get('final_route')" "browser" "최종 경로 = browser"
  assert_stdout_has "OPENREACH-BODY-MARKER" "브라우저가 렌더한 본문 포함 (JS 실행 증거)"
  assert_expr "any(a.get('route') == 'browser' for a in (d.get('attempts') or []))" "True" \
    "attempts 에 browser 경로 기록"
  assert_expr "'moment' not in ((d.get('metadata') or {}).get('title') or '')" "True" \
    "title 이 챌린지 문구('Just a moment')가 아님 — JS 가 실제로 실행됐다"
  assert_expr "len(d.get('content_markdown') or '') >= 200" "True" "본문이 실질 분량"
else
  note "브라우저 미설치: browser_disabled 로 강등한다 (SC-7 — T1 경로는 설치 0)"
  run_engine fetch --allow-browser "$JS_URL"
  assert_code 1 "미설치 강등 종료 코드 1"
  assert_expr "d.get('ok')" "False" "미설치 시 실패 유지"
  assert_expr "d.get('failure_reason')" "waf_challenge" "미설치 시 원 판정(waf_challenge) 유지 — 없는 돌파를 지어내지 않는다"
  assert_expr "any(a.get('route') == 'policy' and a.get('rule') == 'browser_disabled' for a in (d.get('attempts') or []))" "True" \
    "browser_disabled 정책 시도 기록 (NG-10)"
fi

finish
