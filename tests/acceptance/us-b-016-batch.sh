#!/usr/bin/env bash
# US-B-016 — 명시한 목록의 병렬 취득 (R6)
# AC-B-016-1 / -2 / -3 / -4 / -5 / -6
#
# NG-5 가 "단건만"에서 "사용자가 명시한 유한 집합"으로 개정되면서, 이 도구가
# 크롤러가 되지 않게 막는 것은 두 가지뿐이다: **재귀 부재**(US-B-017 이 지킨다)와
# **페이싱**. 그래서 여기서 가장 중요한 단언은 종료코드가 아니라 AC-B-016-3 —
# 워커를 8개 줘도 같은 호스트는 직렬이고 간격 하한을 지킨다는 벽시계 측정이다.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_lib.sh"

LISTS="$WORK/batch"
mkdir -p "$LISTS"

reset_hits() {
  "$PY" - "$BASE" <<'PY' >/dev/null 2>&1 || true
import sys, urllib.request
urllib.request.urlopen(sys.argv[1] + "/_hits/reset", timeout=10).read()
PY
}

hits() { # hits <path> — 선행 슬래시를 떼고 넘긴다 (Git Bash MSYS 경로 변환 회피)
  "$PY" - "$BASE" "${1#/}" <<'PY'
import json, sys, urllib.request
try:
    raw = urllib.request.urlopen(sys.argv[1] + "/_hits", timeout=10).read()
    data = json.loads(raw.decode("utf-8"))
except Exception:
    print("__HITS_ERROR__")
    sys.exit(0)
prefix = "/" + sys.argv[2]
print(sum(v for k, v in data.items() if k.startswith(prefix)))
PY
}

assert_hits() { # assert_hits <path-prefix> <expected> <label>
  local actual
  actual="$(hits "$1")"
  if [ "$actual" != "$2" ]; then
    fail "$3 (path=$1 expected=$2 actual=$actual)"
  fi
}

# NDJSON 은 줄마다 문서라 jexpr(전체를 하나의 JSON 으로 파싱)로는 볼 수 없다.
jline() { # jline <1-based-line> <python-expr>  (d = 그 줄의 객체)
  printf '%s' "${ENG_OUT:-}" | "$PY" -c "
import json, sys
lines = [l for l in sys.stdin.read().splitlines() if l.strip()]
n = $1
if n > len(lines):
    print('__NO_LINE__')
    sys.exit(0)
try:
    d = json.loads(lines[n - 1])
except Exception:
    print('__PARSE_ERROR__')
    sys.exit(0)
try:
    print($2)
except Exception:
    print('__EXPR_ERROR__')
"
}

assert_line() { # assert_line <line> <expr> <expected> <label>
  local actual
  actual="$(jline "$1" "$2")"
  if [ "$actual" != "$3" ]; then
    fail "$4 (line=$1 expr=$2 expected=$3 actual=$actual)"
  fi
}

nlines() {
  printf '%s' "${ENG_OUT:-}" | "$PY" -c \
    "import sys; print(len([l for l in sys.stdin.read().splitlines() if l.strip()]))"
}

assert_lines() { # assert_lines <expected> <label>
  local actual
  actual="$(nlines)"
  if [ "$actual" != "$1" ]; then
    fail "$2 (expected $1 line(s), got $actual)"
  fi
}

# ── 목록 파일 ──────────────────────────────────────────────────────────────

cat > "$LISTS/ok.txt" <<EOF
$BASE/public/article
$BASE/waf/forbidden-but-real
EOF

# 주석·빈 줄·중복 — 셋 다 목록 파일에서 흔하다
cat > "$LISTS/messy.txt" <<EOF
# 첫 줄은 주석이다

$BASE/public/article

$BASE/waf/forbidden-but-real
$BASE/public/article
EOF

cat > "$LISTS/boundary.txt" <<EOF
$BASE/public/article
$BASE/wall/login
EOF

cat > "$LISTS/mixed.txt" <<EOF
$BASE/public/article
$BASE/err/404
EOF

# 같은 호스트 3건. 픽스처는 쿼리를 떼고 라우팅하므로 셋 다 같은 문서를 낸다 —
# 다른 것은 URL 문자열뿐이라 페이싱만 측정된다.
cat > "$LISTS/samehost.txt" <<EOF
$BASE/public/article
$BASE/public/article?a=1
$BASE/public/article?a=2
EOF

"$PY" - "$BASE" "$LISTS/over.txt" <<'PY'
import sys
base, path = sys.argv[1], sys.argv[2]
with open(path, "w", encoding="utf-8") as fh:
    for i in range(51):
        fh.write(f"{base}/public/article?n={i}\n")
PY

# ── AC-B-016-5 / -6: 전부 성공 ─────────────────────────────────────────────

note "AC-B-016-5: URL 당 NDJSON 1줄, 입력 순서 보존"
reset_hits
run_engine fetch --batch "$LISTS/ok.txt"
assert_code 0 "전부 성공인데 0 이 아니다"
assert_lines 2 "AC-B-016-5 출력 줄 수가 입력 URL 수와 다르다"
assert_line 1 "d['url'].endswith('/public/article')" "True" \
  "AC-B-016-1 출력이 입력 순서를 따르지 않았다 (완료 순서로 섞임)"
assert_line 2 "d['url'].endswith('/waf/forbidden-but-real')" "True" \
  "AC-B-016-1 출력이 입력 순서를 따르지 않았다"
assert_line 1 "d.get('ok')" "True" "공개 문서 취득이 배치에서 실패했다"
assert_line 2 "d.get('ok')" "True" "403 이지만 본문이 온 경우가 배치에서 실패했다"

note "AC-B-016-1: 빈 줄·주석은 건너뛰고 중복은 순서 유지한 채 제거"
reset_hits
run_engine fetch --batch "$LISTS/messy.txt"
assert_code 0 "정리된 목록에서 실패했다"
assert_lines 2 "AC-B-016-1 주석·빈 줄·중복 정리가 되지 않았다"
assert_line 1 "d['url'].endswith('/public/article')" "True" "AC-B-016-1 dedupe 가 순서를 바꿨다"

# ── AC-B-016-6: 종료코드 ───────────────────────────────────────────────────

note "AC-B-016-6: 실패가 경계 사유뿐 → exit 2"
reset_hits
run_engine fetch --batch "$LISTS/boundary.txt"
assert_code 2 "경계 사유뿐인 실패가 2 로 나오지 않았다"
assert_lines 2 "AC-B-016-5 부분 실패가 나머지를 중단시켰다"
assert_line 2 "d.get('failure_reason')" "auth_wall" "AC-B-016-6 경계 판정이 배치에서 달라졌다"

note "AC-B-016-6: 경계 아닌 실패가 섞이면 → exit 1"
reset_hits
run_engine fetch --batch "$LISTS/mixed.txt"
assert_code 1 "경계 아닌 실패가 1 로 나오지 않았다"
assert_line 2 "d.get('failure_reason')" "not_found" "AC-B-016-5 배치에서 사유 분류가 달라졌다"

# ── AC-B-016-3: 같은 호스트는 워커 수와 무관하게 직렬 ──────────────────────

note "AC-B-016-3: 같은 호스트 3건 + --concurrency 8 → 간격 하한이 지켜진다"
reset_hits
_started=$SECONDS
run_engine fetch --batch "$LISTS/samehost.txt" --concurrency 8
_elapsed=$((SECONDS - _started))
assert_code 0 "같은 호스트 배치가 실패했다"
assert_lines 3 "AC-B-016-5 출력 줄 수가 다르다"
if [ "$_elapsed" -lt 2 ]; then
  fail "AC-B-016-3 같은 호스트 3건이 ${_elapsed}s 만에 끝났다 — 페이싱이 배치에서 우회됐다"
fi

# ── AC-B-016-2 / -4 / -1: 요청 전에 거부되는 입력 ──────────────────────────

note "AC-B-016-2: url 과 --batch 동시 지정 → exit 4, 요청 0건"
reset_hits
run_engine fetch --batch "$LISTS/ok.txt" "$BASE/public/article"
assert_code 4 "무엇을 가져오라는 것인지 조용히 골라 잡았다"
assert_hits "/public" "0" "AC-B-016-2 사용 오류 판정 전에 요청이 나갔다"

note "AC-B-016-2: 둘 다 없음 → exit 4"
reset_hits
run_engine fetch
assert_code 4 "대상 없는 fetch 가 통과했다"

note "AC-B-016-4: --concurrency 9 → exit 4, 요청 0건"
reset_hits
run_engine fetch --batch "$LISTS/ok.txt" --concurrency 9
assert_code 4 "동시성 상한이 강제되지 않았다"
assert_hits "/public" "0" "AC-B-016-4 상한 판정 전에 요청이 나갔다"

note "AC-B-016-1: 목록 51건 → exit 4, 요청 0건"
reset_hits
run_engine fetch --batch "$LISTS/over.txt"
assert_code 4 "목록 상한 50 이 강제되지 않았다"
assert_hits "/public" "0" "AC-B-016-1 상한 판정 전에 요청이 나갔다"

finish
