#!/usr/bin/env bash
# run.sh — open-reach 동결 인수 테스트 러너
#
# 규약 (auto-complete-loop acceptance-gate):
#   - 마지막 줄: ACCEPTANCE_RESULT: total=N passed=N failed=N
#   - 종료 코드 0은 total >= 1 AND failed == 0 일 때만
#   - 대상 서버(픽스처)의 기동·포트·종료를 이 스크립트가 직접 통제한다
#
# 런타임 산출물은 mktemp -d 로 만든 tests/acceptance/ 밖 디렉토리에만 쓴다
# (동결 해시가 실행 부산물로 깨지지 않게).
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"

emit_and_exit() { # emit_and_exit <total> <passed> <failed> <exit-code>
  echo "ACCEPTANCE_RESULT: total=$1 passed=$2 failed=$3"
  exit "$4"
}

PY=""
for c in python3 python py; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "[run] python interpreter not found" >&2
  emit_and_exit 0 0 0 1
fi

WORK="$(mktemp -d 2>/dev/null || echo "${TMPDIR:-/tmp}/open-reach-acc.$$")"
mkdir -p "$WORK"
PORT_FILE="$WORK/port"
SRV_LOG="$WORK/fixture.log"
SRV_PID=""

cleanup() {
  if [ -n "$SRV_PID" ]; then
    kill "$SRV_PID" 2>/dev/null || true
    wait "$SRV_PID" 2>/dev/null || true
  fi
  rm -rf "$WORK" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

"$PY" "$HERE/fixture_server.py" --port-file "$PORT_FILE" >"$SRV_LOG" 2>&1 &
SRV_PID=$!

# 픽스처 기동 대기 (최대 10초)
for _ in $(seq 1 100); do
  if [ -s "$PORT_FILE" ]; then break; fi
  if ! kill -0 "$SRV_PID" 2>/dev/null; then break; fi
  sleep 0.1
done

if [ ! -s "$PORT_FILE" ]; then
  echo "[run] fixture server failed to start" >&2
  sed -n '1,40p' "$SRV_LOG" >&2 2>/dev/null || true
  emit_and_exit 0 0 0 1
fi

PORT="$(cat "$PORT_FILE")"
export OPENREACH_FIXTURE_BASE="http://127.0.0.1:$PORT"
export OPENREACH_WORK_DIR="$WORK"
export OPENREACH_ROOT="$ROOT"

echo "[run] fixture base = $OPENREACH_FIXTURE_BASE"

total=0
passed=0
failed=0

for t in "$HERE"/us-*.sh; do
  [ -e "$t" ] || continue
  name="$(basename "$t")"
  total=$((total + 1))
  echo "[run] $name"
  if bash "$t" >"$WORK/$name.log" 2>&1; then
    passed=$((passed + 1))
    echo "  PASS"
  else
    failed=$((failed + 1))
    echo "  FAIL"
    sed -n '1,40p' "$WORK/$name.log" 2>/dev/null | sed 's/^/    /'
  fi
done

if [ "$total" -gt 0 ] && [ "$failed" -eq 0 ]; then
  emit_and_exit "$total" "$passed" "$failed" 0
fi
emit_and_exit "$total" "$passed" "$failed" 1
