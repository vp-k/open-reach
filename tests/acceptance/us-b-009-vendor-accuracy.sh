#!/usr/bin/env bash
# us-b-009-vendor-accuracy.sh — 벤더 감지 정확도(AC-B-009-4)와
#                               Phase 0 이후에도 남는 HTTP 돌파율(AC-B-010-16·17).
#
# 이 파일이 지키는 것 하나: **돌파율이 올랐을 때 그 출처를 출력만 보고 갈라낼 수 있다.**
# rate 만 있으면 전송이 좋아진 것과 API 가 구해 준 것이 같은 숫자로 보인다.
set -uo pipefail
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_lib.sh"

FIX="$ROOT/tests/fixtures"

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

line_of() { # line_of <prefix> — bench 출력에서 해당 접두 줄
  printf '%s\n' "${ENG_OUT:-}" | grep -a "^$1" | head -n 1
}

# ── AC-B-009-4: 정답 라벨과 감지값의 대조가 출력에 나온다 ────────────────
LOCAL_BATTERY="$(materialize battery-local.yaml)"

note "AC-B-009-4: vendor_accuracy 분해가 존재한다"
run_engine bench --battery "$LOCAL_BATTERY" --runs 1 --no-browser
assert_code 0 "정상 배터리 exit 0"
assert_stdout_has "vendor_accuracy: " "AC-B-009-4 vendor_accuracy 분해 부재"
assert_stdout_has "vendor_misses: " "AC-B-009-4 오분류 목록 부재"

acc="$(line_of 'vendor_accuracy: ')"
for key in correct false_positive false_negative unresolved unmeasured; do
  case "$acc" in
    *"\"$key\""*) : ;;
    *) fail "AC-B-009-4 처분 키 누락: $key ($acc)" ;;
  esac
done

# 건수를 **정확히** 못 박는다. `false_positive == 0` 만 보면 감지 경로를 통째로
# 망가뜨려 전 항목을 `unmeasured` 로 만드는 변형(예: 벤더를 늘 None 으로 돌려주기)이
# 오탐 0건으로 통과한다 — 실패할 수 없는 단언이 된다.
# 픽스처 6항목은 전부 라벨과 감지값이 맞아야 한다.
acc_json="$(printf '%s' "$acc" | "$PY" -c "
import json, sys
raw = sys.stdin.read().split(': ', 1)
try:
    data = json.loads(raw[1])
    print(' '.join(str(data.get(k)) for k in
          ('correct', 'false_positive', 'false_negative', 'unresolved', 'unmeasured')))
except Exception:
    print('__PARSE_ERROR__')
")"
[ "$acc_json" = "6 0 0 0 0" ] || fail "AC-B-009-4 픽스처 배터리 정확도가 다르다 (correct fp fn unresolved unmeasured = $acc_json)"

# SC-8 요약(분모 포함)이 출력에 있어야 한다. 분모 없이 "미탐 0건"만 적으면
# 잘 맞힌 것과 한 건도 재지 못한 것이 같은 줄로 보인다.
assert_stdout_has "vendor_sc8: " "SC-8 요약 줄 부재"
sc8="$(line_of 'vendor_sc8: ')"
case "$sc8" in
  *'"measurable": 6'*|*'"measurable":6'*) note "$sc8" ;;
  *) fail "SC-8 분모가 6이 아니다: ${sc8:-<부재>}" ;;
esac

note "SC-8: 미탐율이 한계를 넘으면 bench 가 exit 3 으로 막는다"
MISS_BATTERY="$(materialize battery-sc8-miss.yaml)"
run_engine bench --battery "$MISS_BATTERY" --runs 1 --no-browser
# 6건 중 1건 미탐 = 16.7% > 10%. 게이트를 지우면 이 단언이 먼저 깨진다.
assert_code 3 "SC-8 미탐율 초과가 통과했다"
# _lib.sh 는 동결돼 있어 헬퍼를 늘리지 않는다 — 여기서 직접 본다.
case "${ENG_ERR:-}" in
  *"SC-8"*) : ;;
  *) fail "SC-8 위반 사유가 stderr 에 없다 (${ENG_ERR:0:200})" ;;
esac

# ── AC-B-010-16·17: Phase 0 을 켜도 HTTP 돌파율이 사라지지 않는다 ───────
RESCUE_BATTERY="$(materialize battery-phase0-rescue.yaml)"
RESCUE_INDEX="$(materialize api-index-rescue.yaml)"

note "AC-B-010-16·17: 구제 1건 + HTTP 성공 1건을 갈라 낸다"
# 함수 호출 앞의 변수 대입은 bash 에서 호출이 끝난 뒤에도 남는다 — 마지막 검사가
# 인덱스를 그대로 물려받으면 "인덱스 없음"을 재지 못한다. 명시적으로 걸고 명시적으로 뺀다.
export OPENREACH_API_INDEX="$RESCUE_INDEX"
run_engine bench --battery "$RESCUE_BATTERY" --runs 1 --no-browser
assert_code 0 "구제 배터리 exit 0"

last_line="$(printf '%s\n' "${ENG_OUT:-}" | tail -n 1)"
case "$last_line" in
  "BENCH_RESULT: rate=1.000 total=2 passed=2 failed=0") note "양성 2건 모두 성공" ;;
  *) fail "AC-B-010-17 전제 불성립 — 두 건 모두 성공해야 한다: $last_line" ;;
esac

split="$(line_of 'rate_http_only=')"
case "$split" in
  # 분모는 양성 2건, HTTP 로 얻은 것은 1건이다. 이 값이 rate 와 같아지면
  # Phase 0 성공이 HTTP 실력으로 계상되고 있다는 뜻이다 (R2 종료 조건이 무의미해진다).
  "rate_http_only=0.500 rescued_by_phase0=1") note "$split" ;;
  *) fail "AC-B-010-16·17 분리 실패: ${split:-<부재>}" ;;
esac

assert_stdout_has '"phase0"' "AC-B-010-17 by_route 에 phase0 이 없다"

# ── 인덱스가 없으면 구제도 없다 — 같은 배터리가 다른 수치를 낸다 ────────
note "인덱스를 빼면 구제가 사라진다 (수치가 인덱스에서 온다는 증거)"
unset OPENREACH_API_INDEX
run_engine bench --battery "$RESCUE_BATTERY" --runs 1 --no-browser
assert_code 0 "인덱스 없이도 실행 자체는 된다"
split2="$(line_of 'rate_http_only=')"
case "$split2" in
  *"rescued_by_phase0=0") note "$split2" ;;
  *) fail "인덱스 없이 구제가 계상됐다: ${split2:-<부재>}" ;;
esac

# ── H1: 인덱스가 깨져 있으면 배터리 요청이 **한 건도** 나가지 않는다 ───
note "AC-B-010-15: bench 도 요청 전에 인덱스를 검증한다"
BAD_INDEX="$WORK/api-index-broken.yaml"
cat > "$BAD_INDEX" <<'YAML'
# verified_at 누락 — 로드 실패(exit 3) 대상이다.
entries:
  - host: 127.0.0.1
    url_pattern: "^/public/"
    source: "https://example.invalid/fixture-api-docs"
    response_kind: html
    endpoints:
      - "http://127.0.0.1:1/never"
YAML
"$PY" - "$BASE" <<'PY'
import sys, urllib.request
urllib.request.urlopen(sys.argv[1] + "/_hits/reset", timeout=10).read()
PY
export OPENREACH_API_INDEX="$BAD_INDEX"
run_engine bench --battery "$LOCAL_BATTERY" --runs 1 --no-browser
unset OPENREACH_API_INDEX
assert_code 3 "깨진 인덱스로 bench 가 통과했다"
after="$("$PY" - "$BASE" <<'PY'
import json, sys, urllib.request
try:
    raw = urllib.request.urlopen(sys.argv[1] + "/_hits", timeout=10).read()
    data = json.loads(raw.decode("utf-8"))
except Exception:
    print("__HITS_ERROR__")
else:
    # 계수 조회(`/_hits`) 자체도 서버가 센다 — 그것까지 더하면 이 단언은 절대 0이
    # 되지 않아 항상 실패한다. 배터리가 두드리는 경로만 센다.
    print(sum(v for k, v in data.items() if not k.startswith("/_hits")))
PY
)"
# 배터리를 절반쯤 돈 뒤에 인덱스 오류를 발견하면 이미 나간 요청은 되돌릴 수 없다.
[ "$after" = "0" ] || fail "AC-B-010-15 인덱스 검증 전에 요청이 나갔다 (hits=$after)"

finish
