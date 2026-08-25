# _lib.sh — 인수 테스트 공용 헬퍼 (us-*.sh 가 source 한다)
#
# 이 파일은 us-*.sh 글롭에 걸리지 않으므로 테스트로 계상되지 않는다.
# shellcheck shell=bash

set -uo pipefail

: "${OPENREACH_FIXTURE_BASE:?[_lib] OPENREACH_FIXTURE_BASE not set (run via run.sh)}"

ACC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${OPENREACH_ROOT:-$(cd "$ACC_DIR/../.." && pwd)}"
WORK="${OPENREACH_WORK_DIR:-$(mktemp -d)}"
BASE="$OPENREACH_FIXTURE_BASE"

PY=""
for _c in python3 python py; do
  if command -v "$_c" >/dev/null 2>&1; then PY="$_c"; break; fi
done
if [ -z "$PY" ]; then
  echo "  ASSERT FAIL: python interpreter not found" >&2
  exit 1
fi

export PYTHONPATH="$ROOT/skills/open-reach${PYTHONPATH:+:$PYTHONPATH}"

FAILURES=0
ENG_OUT=""
ENG_ERR=""
ENG_CODE=0

note() { echo "  - $*"; }
fail() { echo "  ASSERT FAIL: $*" >&2; FAILURES=$((FAILURES + 1)); }

# run_engine <args...> — ENG_OUT / ENG_ERR / ENG_CODE 를 채운다
run_engine() {
  local err_file="$WORK/.stderr.$$"
  ENG_OUT="$("$PY" -m open_reach.engine "$@" 2>"$err_file")"
  ENG_CODE=$?
  ENG_ERR="$(cat "$err_file" 2>/dev/null || true)"
  rm -f "$err_file"
  return 0
}

# jexpr <python-expr> — ENG_OUT 을 JSON 으로 파싱해 표현식 결과를 출력한다 (d = 파싱된 객체)
jexpr() {
  printf '%s' "${ENG_OUT:-}" | "$PY" -c "
import json, sys
raw = sys.stdin.read()
try:
    d = json.loads(raw)
except Exception:
    print('__PARSE_ERROR__')
    sys.exit(0)
try:
    print($1)
except Exception:
    print('__EXPR_ERROR__')
"
}

assert_code() { # assert_code <expected> <label>
  if [ "$ENG_CODE" != "$1" ]; then
    fail "$2 (expected exit $1, got $ENG_CODE; stderr: ${ENG_ERR:0:200})"
  fi
}

assert_expr() { # assert_expr <python-expr> <expected> <label>
  local actual
  actual="$(jexpr "$1")"
  if [ "$actual" != "$2" ]; then
    fail "$3 (expr=$1 expected=$2 actual=$actual)"
  fi
}

assert_stdout_has() { # assert_stdout_has <needle> <label>
  case "${ENG_OUT:-}" in
    *"$1"*) : ;;
    *) fail "$2 (stdout missing: $1)" ;;
  esac
}

assert_stdout_lacks() { # assert_stdout_lacks <needle> <label>
  case "${ENG_OUT:-}" in
    *"$1"*) fail "$2 (stdout must not contain: $1)" ;;
    *) : ;;
  esac
}

finish() {
  if [ "$FAILURES" -eq 0 ]; then
    echo "  OK"
    exit 0
  fi
  echo "  $FAILURES assertion(s) failed" >&2
  exit 1
}
