#!/usr/bin/env bash
# US-B-004 — 돌파율 산출
# AC-B-004-1 / -2 / -3 / -4 / -5
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_lib.sh"

FIX="$ROOT/tests/fixtures"
STATE="$WORK/state-004"
mkdir -p "$STATE"
export OPENREACH_STATE_DIR="$STATE"

# 픽스처 배터리의 __FIXTURE_BASE__ 를 실제 base URL 로 치환한 사본을 $WORK 에 만든다
materialize() { # materialize <fixture-name> -> 경로를 출력
  local src="$FIX/$1"
  local dst="$WORK/$1"
  "$PY" - "$src" "$dst" "$BASE" <<'PYEOF'
import sys, pathlib
src, dst, base = sys.argv[1], sys.argv[2], sys.argv[3]
pathlib.Path(dst).write_text(
    pathlib.Path(src).read_text(encoding="utf-8").replace("__FIXTURE_BASE__", base),
    encoding="utf-8",
)
PYEOF
  echo "$dst"
}

LOCAL_BATTERY="$(materialize battery-local.yaml)"

note "AC-B-004-1: BENCH_RESULT 마지막 줄 + 분해 3종 선행"
run_engine bench --battery "$LOCAL_BATTERY" --runs 1 --no-browser
assert_code 0 "정상 배터리 exit 0"

last_line="$(printf '%s' "${ENG_OUT:-}" | tail -n 1)"
case "$last_line" in
  "BENCH_RESULT: rate="*" total="*" passed="*" failed="*) note "BENCH_RESULT 형식 확인" ;;
  *) fail "AC-B-004-1 마지막 줄이 BENCH_RESULT 형식이 아님: $last_line" ;;
esac

body_before_last="$(printf '%s' "${ENG_OUT:-}" | sed '$d')"
for key in by_vendor by_route by_reason; do
  case "$body_before_last" in
    *"$key"*) : ;;
    *) fail "AC-B-004-1 분해 누락: $key" ;;
  esac
done

note "AC-B-004-4: history.jsonl append-only"
HIST="$STATE/bench/history.jsonl"
before=0
[ -f "$HIST" ] && before="$(wc -l < "$HIST" | tr -d ' ')"
run_engine bench --battery "$LOCAL_BATTERY" --runs 1 --no-browser
after=0
[ -f "$HIST" ] && after="$(wc -l < "$HIST" | tr -d ' ')"
if [ "$after" != "$((before + 1))" ]; then
  fail "AC-B-004-4 history.jsonl 이 1줄 증가하지 않음 (before=$before after=$after)"
fi

note "AC-B-004-2: G-1 위반 (role=production, 벤더 커버리지 미달) → exit 3"
G1="$(materialize battery-g1-violation.yaml)"
run_engine bench --battery "$G1" --runs 1 --no-browser
assert_code 3 "G-1 위반 exit 3"
case "$ENG_ERR" in *G-1*) : ;; *) fail "AC-B-004-2 stderr 에 G-1 미표기" ;; esac

note "AC-B-004-2: G-3 위반 (음성 케이스 0건) → exit 3"
G3="$(materialize battery-g3-violation.yaml)"
run_engine bench --battery "$G3" --runs 1 --no-browser
assert_code 3 "G-3 위반 exit 3"
case "$ENG_ERR" in *G-3*) : ;; *) fail "AC-B-004-2 stderr 에 G-3 미표기" ;; esac

note "AC-B-004-2: G-4 위반 (필수 필드 누락) → exit 3"
G4="$(materialize battery-g4-violation.yaml)"
run_engine bench --battery "$G4" --runs 1 --no-browser
assert_code 3 "G-4 위반 exit 3"
case "$ENG_ERR" in *G-4*) : ;; *) fail "AC-B-004-2 stderr 에 G-4 미표기" ;; esac

note "AC-B-004-2: G-6 위반 (Tier-1 항목 51개) → exit 3"
G6="$WORK/battery-g6-violation.yaml"
"$PY" - "$LOCAL_BATTERY" "$G6" <<'PYEOF'
import sys, pathlib, re
src, dst = sys.argv[1], sys.argv[2]
text = pathlib.Path(src).read_text(encoding="utf-8")
head, _, entries = text.partition("entries:\n")
blocks = [b for b in re.split(r"(?=\n?  - id: )", entries) if b.strip()]
positive = next(b for b in blocks if "negative_case: null" in b)
negative = next(b for b in blocks if "negative_case: auth_wall" in b)
out = [head, "entries:\n"]
for i in range(50):
    out.append(positive.replace("id: public-article", f"id: bulk-{i:03d}").lstrip("\n"))
out.append(negative.lstrip("\n"))
pathlib.Path(dst).write_text("".join(out), encoding="utf-8")
PYEOF
run_engine bench --battery "$G6" --runs 1 --no-browser
assert_code 3 "G-6 위반 exit 3"
case "$ENG_ERR" in *G-6*) : ;; *) fail "AC-B-004-2 stderr 에 G-6 미표기" ;; esac

note "AC-B-004-3: 음성 케이스가 success 로 분류되면 벤치 전체 fail"
# 음성 케이스(로그인월)를 정답 대조 대상으로 바꾼 배터리 — 엔진이 이를 success 로 계상하면 exit 3 이어야 한다
MISCLASS="$WORK/battery-negative-as-positive.yaml"
"$PY" - "$LOCAL_BATTERY" "$MISCLASS" <<'PYEOF'
import sys, pathlib
src, dst = sys.argv[1], sys.argv[2]
text = pathlib.Path(src).read_text(encoding="utf-8")
pathlib.Path(dst).write_text(text.replace("negative_case: auth_wall", "negative_case: paywall"), encoding="utf-8")
PYEOF
run_engine bench --battery "$MISCLASS" --runs 1 --no-browser
assert_code 3 "음성 케이스 오분류 exit 3"

note "AC-B-008-4: expected 대조 실패는 validation_failed 로 계상"
MM="$(materialize battery-expected-mismatch.yaml)"
run_engine bench --battery "$MM" --runs 1 --no-browser
case "${ENG_OUT:-}" in *validation_failed*) : ;; *) fail "AC-B-008-4 by_reason 에 validation_failed 부재" ;; esac

note "AC-B-004-5: 셔플 실행이 순서 실행과 dead-band 3%p 이내"
run_engine bench --battery "$LOCAL_BATTERY" --runs 1 --no-browser
ordered="$(printf '%s' "${ENG_OUT:-}" | tail -n 1 | sed -n 's/.*rate=\([0-9.]*\).*/\1/p')"
run_engine bench --battery "$LOCAL_BATTERY" --runs 1 --no-browser --shuffle
shuffled="$(printf '%s' "${ENG_OUT:-}" | tail -n 1 | sed -n 's/.*rate=\([0-9.]*\).*/\1/p')"
if [ -z "$ordered" ] || [ -z "$shuffled" ]; then
  fail "AC-B-004-5 rate 값을 읽지 못함 (ordered='$ordered' shuffled='$shuffled')"
elif ! "$PY" -c "import sys; sys.exit(0 if abs(float('$ordered') - float('$shuffled')) <= 0.03 else 1)"; then
  fail "AC-B-004-5 셔플 실행 차이가 dead-band 초과 (ordered=$ordered shuffled=$shuffled)"
fi

note "인자 오류: --runs 0 → exit 4"
run_engine bench --battery "$LOCAL_BATTERY" --runs 0
assert_code 4 "--runs 0 exit 4"

finish
