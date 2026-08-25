#!/usr/bin/env bash
# US-B-005 — 원본 대조
# AC-B-005-1 / -2 / -3
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_lib.sh"

FIX="$ROOT/tests/fixtures"
STATE="$WORK/state-005"
mkdir -p "$STATE"
export OPENREACH_STATE_DIR="$STATE"

BATTERY="$WORK/battery-local-005.yaml"
"$PY" - "$FIX/battery-local.yaml" "$BATTERY" "$BASE" <<'PYEOF'
import sys, pathlib
src, dst, base = sys.argv[1], sys.argv[2], sys.argv[3]
pathlib.Path(dst).write_text(
    pathlib.Path(src).read_text(encoding="utf-8").replace("__FIXTURE_BASE__", base),
    encoding="utf-8",
)
PYEOF

note "AC-B-005-2: 원본을 실행할 수 없으면 unmeasurable + exit 0"
OUT1="$WORK/compare-unmeasurable.json"
run_engine compare --battery "$BATTERY" --original-cmd "open-reach-original-not-installed" --out "$OUT1"
assert_code 0 "원본 미설치 exit 0"
assert_expr "d.get('status')" "unmeasurable" "AC-B-005-2 status=unmeasurable"
assert_expr "bool(d.get('reason'))" "True" "AC-B-005-2 reason non-null"

note "AC-B-005-1: 증적 6필드"
for field in original_commit ran_at os arch python battery_hash; do
  assert_expr "'$field' in (d.get('evidence') or {})" "True" "AC-B-005-1 evidence.$field 존재"
done

note "증적 파일이 --out 경로에 저장된다"
if [ ! -f "$OUT1" ]; then
  fail "AC-B-005-1 증적 파일이 생성되지 않음: $OUT1"
fi

note "AC-B-005-3: 출력 파일 선점 시 덮어쓰지 않고 exit 4"
GUARD="$WORK/compare-guard.json"
printf '%s' '{"sentinel":"do-not-overwrite"}' > "$GUARD"
run_engine compare --battery "$BATTERY" --original-cmd "open-reach-original-not-installed" --out "$GUARD"
assert_code 4 "AC-B-005-3 선점된 출력 파일 exit 4"
if ! grep -qF 'do-not-overwrite' "$GUARD" 2>/dev/null; then
  fail "AC-B-005-3 기존 파일이 덮어써짐"
fi

note "배터리 파일이 없으면 exit 4"
run_engine compare --battery "$WORK/does-not-exist.yaml" --out "$WORK/compare-missing.json"
assert_code 4 "배터리 부재 exit 4"

finish
