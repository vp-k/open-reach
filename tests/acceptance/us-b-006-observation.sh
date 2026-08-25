#!/usr/bin/env bash
# US-B-006 — 성공 경로 재사용 (관측 기록 · 정규화 · 금지 필드 · 우선순위 · 경계 미학습)
# AC-B-006-1 / -2 / -3 / -4 / -5
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_lib.sh"

STATE="$WORK/state-006"
rm -rf "$STATE"
mkdir -p "$STATE"
export OPENREACH_STATE_DIR="$STATE"
OBS="$STATE/observations.jsonl"

count_obs() {
  if [ -f "$OBS" ]; then wc -l < "$OBS" | tr -d ' '; else echo 0; fi
}

note "AC-B-006-1: 성공한 시도가 Observation 1건을 append"
before="$(count_obs)"
run_engine fetch "$BASE/public/article?utm_source=test&sid=abc#frag"
assert_code 0 "성공 fetch exit 0"
after="$(count_obs)"
if [ "$after" != "$((before + 1))" ]; then
  fail "AC-B-006-1 관측이 1건 증가하지 않음 (before=$before after=$after)"
fi

note "AC-B-006-2: URL 정규화 — query/fragment/userinfo 제거"
if [ -f "$OBS" ]; then
  if grep -qF 'utm_source' "$OBS" 2>/dev/null || grep -qF 'sid=abc' "$OBS" 2>/dev/null; then
    fail "AC-B-006-2 query 문자열이 관측에 기록됨"
  fi
  if grep -qF 'frag' "$OBS" 2>/dev/null; then
    fail "AC-B-006-2 fragment 가 관측에 기록됨"
  fi
else
  fail "AC-B-006-2 관측 파일이 없음: $OBS"
fi

note "AC-B-006-3: 허용 필드 화이트리스트 (8키) + 금지 문자열 부재"
if [ -f "$OBS" ]; then
  "$PY" - "$OBS" <<'PYEOF'
import json, sys, pathlib
allowed = {"ts", "host", "path", "waf_vendor", "route", "impersonate", "url_variant", "outcome"}
bad = []
for i, line in enumerate(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").splitlines(), 1):
    line = line.strip()
    if not line:
        continue
    try:
        rec = json.loads(line)
    except Exception:
        bad.append(f"line {i}: not JSON")
        continue
    extra = set(rec) - allowed
    if extra:
        bad.append(f"line {i}: 화이트리스트 밖 키 {sorted(extra)}")
    if rec.get("outcome") != "success":
        bad.append(f"line {i}: outcome 이 success 가 아님 ({rec.get('outcome')})")
if bad:
    print("\n".join(bad))
    sys.exit(1)
PYEOF
  if [ $? -ne 0 ]; then
    fail "AC-B-006-3 관측 스키마 위반"
  fi
  for forbidden in Set-Cookie set_cookie Authorization authorization Cookie fixture_clearance; do
    if grep -qF "$forbidden" "$OBS" 2>/dev/null; then
      fail "AC-B-006-3 금지 문자열이 관측에 기록됨: $forbidden"
    fi
  done
fi

note "AC-B-006-4: 재조회 시 직전 성공 경로가 attempts[0]"
prev_route="$("$PY" - "$OBS" <<'PYEOF'
import json, sys, pathlib
lines = [l for l in pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").splitlines() if l.strip()]
print(json.loads(lines[-1]).get("route", "") if lines else "")
PYEOF
)"
run_engine fetch "$BASE/public/article"
assert_code 0 "재조회 exit 0"
if [ -n "$prev_route" ]; then
  assert_expr "(d.get('attempts') or [{}])[0].get('route')" "$prev_route" "AC-B-006-4 직전 성공 경로가 attempts[0]"
fi

note "AC-B-006-5: 경계 도달 경로는 학습되지 않는다"
before="$(count_obs)"
run_engine fetch "$BASE/wall/login"
assert_code 2 "로그인월 exit 2"
after="$(count_obs)"
if [ "$after" != "$before" ]; then
  fail "AC-B-006-5 auth_wall 경로가 관측에 학습됨 (before=$before after=$after)"
fi

before="$(count_obs)"
run_engine fetch "http://127.0.0.1:1/x"
after="$(count_obs)"
if [ "$after" != "$before" ]; then
  fail "AC-B-006-5 policy_blocked 경로가 관측에 학습됨"
fi

finish
