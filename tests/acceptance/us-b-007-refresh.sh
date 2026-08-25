#!/usr/bin/env bash
# US-B-007 — 지문표 자동 갱신
# AC-B-007-1 / -2 / -3 / -4
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_lib.sh"

STATE="$WORK/state-007"
rm -rf "$STATE"
mkdir -p "$STATE"
export OPENREACH_STATE_DIR="$STATE"

SRC_PROFILES="$ROOT/skills/open-reach/engine/profiles.yaml"
PROFILES="$WORK/profiles-007.yaml"
if [ ! -f "$SRC_PROFILES" ]; then
  fail "지문표가 없음: $SRC_PROFILES"
  finish
fi
cp "$SRC_PROFILES" "$PROFILES"
export OPENREACH_PROFILES="$PROFILES"

hash_of() { "$PY" -c "
import hashlib, sys
print(hashlib.sha256(open(sys.argv[1],'rb').read().replace(b'\r\n', b'\n')).hexdigest())
" "$1"; }

note "AC-B-007-4: 관측 0건이면 파일을 수정하지 않고 no observations + exit 0"
h0="$(hash_of "$PROFILES")"
run_engine refresh
assert_code 0 "관측 0건 exit 0"
assert_stdout_has "no observations" "AC-B-007-4 no observations 출력"
if [ "$(hash_of "$PROFILES")" != "$h0" ]; then
  fail "AC-B-007-4 관측 0건인데 지문표가 변경됨"
fi

note "관측 축적"
run_engine fetch "$BASE/public/article"
assert_code 0 "관측 축적용 fetch exit 0"
run_engine fetch "$BASE/waf/forbidden-but-real"

note "AC-B-007-1 + --dry-run: diff 출력 · 파일 불변"
h1="$(hash_of "$PROFILES")"
run_engine refresh --dry-run
assert_code 0 "--dry-run exit 0"
if [ -z "${ENG_OUT:-}" ]; then
  fail "AC-B-007-1 --dry-run 이 diff 를 출력하지 않음"
fi
if [ "$(hash_of "$PROFILES")" != "$h1" ]; then
  fail "--dry-run 이 지문표를 수정함"
fi

note "AC-B-007-1: 실제 refresh 가 diff 를 출력"
run_engine refresh
assert_code 0 "refresh exit 0"
if [ -z "${ENG_OUT:-}" ]; then
  fail "AC-B-007-1 refresh 가 diff 를 출력하지 않음"
fi

note "AC-B-007-2: last_reviewed 가 실행 일자로 갱신"
today="$("$PY" -c "import datetime; print(datetime.datetime.now(datetime.timezone.utc).date().isoformat())")"
if ! grep -qF "$today" "$PROFILES" 2>/dev/null; then
  fail "AC-B-007-2 last_reviewed 가 오늘($today)로 갱신되지 않음"
fi

note "AC-B-007-3: 원자적 기록 — 임시 파일 잔존 없음"
leftovers="$(find "$(dirname "$PROFILES")" -maxdepth 1 -name '*.tmp*' -o -maxdepth 1 -name '.*profiles*' 2>/dev/null | wc -l | tr -d ' ')"
if [ "$leftovers" != "0" ]; then
  fail "AC-B-007-3 임시 파일이 남아 있음 ($leftovers 개)"
fi

note "AC-B-006-5 연계: 경계 위반 관측은 후보 순서에 반영되지 않는다"
run_engine fetch "$BASE/wall/login"
h2="$(hash_of "$PROFILES")"
run_engine refresh
if [ "$(hash_of "$PROFILES")" != "$h2" ]; then
  fail "경계 위반(auth_wall) 관측이 지문표 갱신에 반영됨"
fi

finish
