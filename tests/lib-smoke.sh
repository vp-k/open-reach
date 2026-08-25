#!/usr/bin/env bash
# lib-smoke.sh — open-reach 라이브러리/CLI 스모크
#
# 목적: 엔진이 "설치된 상태에서 최소한 살아 있는가"만 확인한다.
#   - 패키지 임포트 가능
#   - CLI 서브커맨드 6종이 --help 에 응답 (사용 오류 종료 코드 4 규약 포함)
#   - curl_cffi 계약: impersonate 후보 목록이 비어있지 않다
#
# 이 스크립트는 기능 검증이 아니다. 기능 검증은 tests/acceptance/ 와 tests/unit/ 이 담당한다.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"

PY=""
for c in python3 python py; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "[lib-smoke] FAIL: python interpreter not found" >&2
  exit 1
fi

export PYTHONPATH="$ROOT/skills/open-reach${PYTHONPATH:+:$PYTHONPATH}"

fails=0
check() {
  local label="$1"; shift
  if "$@" >/dev/null 2>&1; then
    echo "[lib-smoke] ok   - $label"
  else
    echo "[lib-smoke] FAIL - $label" >&2
    fails=$((fails + 1))
  fi
}

# 1) 패키지 임포트
check "import open_reach.engine" "$PY" -c "import open_reach.engine"

# 2) CLI 서브커맨드 --help
for sub in fetch bench compare baseline refresh explain; do
  check "engine $sub --help" "$PY" -m open_reach.engine "$sub" --help
done

# 3) 사용 오류는 종료 코드 4
"$PY" -m open_reach.engine fetch --timeout 0 "http://example.invalid/" >/dev/null 2>&1
code=$?
if [ "$code" -eq 4 ]; then
  echo "[lib-smoke] ok   - usage error exits 4"
else
  echo "[lib-smoke] FAIL - usage error expected exit 4, got $code" >&2
  fails=$((fails + 1))
fi

# 4) curl_cffi 계약
check "curl_cffi impersonate candidates non-empty" "$PY" -c "
import curl_cffi.requests as r
names = [x for x in dir(r) if 'impersonate' in x.lower()]
assert names, 'no impersonate surface on curl_cffi.requests'
"

if [ "$fails" -eq 0 ]; then
  echo "[lib-smoke] PASS"
  exit 0
fi
echo "[lib-smoke] FAIL ($fails checks failed)" >&2
exit 1
