#!/usr/bin/env bash
# US-B-017 — 질의로 후보 URL 모으기 (R6)
# AC-B-017-1 / -2 / -3 / -4 / -5 / -8
#
# 검색 계층이 생기면서 이 도구는 "준 URL 을 가져오는 것"에서 "URL 을 찾아 가져오는
# 것"이 됐다. 크롤러와 가르는 선은 하나뿐이다 — **취득한 본문의 링크는 후보가 되지
# 않는다**. 그래서 여기서는 동작(취득 문서마다 링크가 있는데 후보가 늘지 않는다)과
# 구조(후보 생성 모듈이 취득·추출 계층을 임포트하지 않는다)를 함께 고정한다.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_lib.sh"

IDX="$WORK/idx-b017"
mkdir -p "$IDX"

NETLOC="${BASE#http://}"

write_index() {
  sed -e "s|__BASE__|$BASE|g" -e "s|__NETLOC__|$NETLOC|g" > "$IDX/$1"
}

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

# ── 인덱스 ─────────────────────────────────────────────────────────────────
# entries 는 로더의 최상위 요건을 채우는 들러리다 — 이 테스트의 어떤 입력에도
# 매치하지 않으므로 phase0 구제가 판정에 끼어들지 않는다.

write_index srch.yaml <<'YAML'
entries:
  - host: __NETLOC__
    url_pattern: "^/api/origin/(?P<name>[a-z0-9]+)$"
    source: "https://example.invalid/api-docs"
    verified_at: "2026-09-02"
    response_kind: html
    endpoints:
      - "__BASE__/api/step2/{name}"
search_sources:
  - name: jsonsrc
    host: __NETLOC__
    kind: json
    query_template: "__BASE__/srch/json?q={query}"
    result_pointer: hits
    link_pointer: link
    title_pointer: name
    source: "https://example.invalid/search-api"
    verified_at: "2026-09-02"
  - name: jsondup
    host: __NETLOC__
    kind: json
    query_template: "__BASE__/srch/json2?q={query}"
    result_pointer: hits
    link_pointer: link
    source: "https://example.invalid/search-api"
    verified_at: "2026-09-02"
  - name: htmlsrc
    host: __NETLOC__
    kind: html
    query_template: "__BASE__/srch/html?q={query}"
    result_link_pattern: '<a class="r" href="([^"]+)">'
    link_transform: none
    source: "https://example.invalid/search-html"
    verified_at: "2026-09-02"
  - name: emptysrc
    host: __NETLOC__
    kind: json
    query_template: "__BASE__/srch/empty?q={query}"
    result_pointer: hits
    link_pointer: link
    source: "https://example.invalid/search-api"
    verified_at: "2026-09-02"
YAML

# ── AC-B-017-4: --urls-only 는 취득을 하지 않는다 ──────────────────────────

note "AC-B-017-4 / -2 / -8: 두 소스 fan-out → 요약 1줄, dedupe, 취득 요청 0건"
reset_hits
run_engine search --api-index "$IDX/srch.yaml" --sources jsonsrc,jsondup \
  --max-results 25 --urls-only rust
assert_code 0 "--urls-only 검색이 실패했다"
if [ "$(nlines)" != "1" ]; then
  fail "AC-B-017-4 --urls-only 인데 요약 외의 줄이 나왔다 (취득이 일어났다)"
fi
assert_line 1 "len(d['search']['candidates'])" "12" \
  "AC-B-017-2 겹치는 후보가 dedupe 되지 않았다 (12건이어야 한다)"
assert_line 1 "len(set(c['url'] for c in d['search']['candidates'])) == len(d['search']['candidates'])" \
  "True" "AC-B-017-2 후보에 중복 URL 이 남았다"
assert_line 1 "len(d['search']['sources'])" "2" "AC-B-017-8 소스별 성패가 요약에 남지 않았다"
assert_hits "/doc/" "0" "AC-B-017-4 --urls-only 인데 후보 URL 을 두드렸다"

note "AC-B-017-2: --max-results 3 → 인터리브 후 절단"
reset_hits
run_engine search --api-index "$IDX/srch.yaml" --sources jsonsrc \
  --max-results 3 --urls-only rust
assert_code 0 "절단 검색이 실패했다"
assert_line 1 "len(d['search']['candidates'])" "3" "AC-B-017-2 상한 절단이 되지 않았다"

# ── AC-B-017-5: 질의는 URL 구조를 바꿀 수 없다 ─────────────────────────────

note "AC-B-017-5: 질의의 &·= 는 퍼센트 인코딩된다"
reset_hits
run_engine search --api-index "$IDX/srch.yaml" --sources jsonsrc --urls-only "rust&x=1"
assert_code 0 "인코딩 대상 질의가 실패했다"
assert_line 1 "d['search']['sources'][0]['endpoint'].count('&')" "0" \
  "AC-B-017-5 질의가 쿼리 파라미터를 하나 더 만들었다 (구조 변경)"
assert_line 1 "'%26' in d['search']['sources'][0]['endpoint']" "True" \
  "AC-B-017-5 질의가 퍼센트 인코딩되지 않았다"

note "AC-B-017-5: 질의 길이 상한(256자) 초과 → exit 4, 요청 0건"
reset_hits
_LONGQ="$("$PY" -c "print('q' * 257)")"
run_engine search --api-index "$IDX/srch.yaml" --urls-only "$_LONGQ"
assert_code 4 "질의 길이 상한이 강제되지 않았다"
assert_hits "/srch" "0" "AC-B-017-5 상한 판정 전에 요청이 나갔다"

# ── AC-B-017-1: 모르는 소스는 요청 전에 거부 ───────────────────────────────

note "AC-B-017-1: 모르는 소스 이름 → exit 4, 요청 0건"
reset_hits
run_engine search --api-index "$IDX/srch.yaml" --sources nosuch --urls-only rust
assert_code 4 "모르는 소스 이름이 통과했다"
assert_hits "/srch" "0" "AC-B-017-1 소스 판정 전에 요청이 나갔다"

note "AC-B-017-2: --max-results 26 → exit 4, 요청 0건"
reset_hits
run_engine search --api-index "$IDX/srch.yaml" --max-results 26 --urls-only rust
assert_code 4 "후보 상한 25 가 강제되지 않았다"
assert_hits "/srch" "0" "AC-B-017-2 상한 판정 전에 요청이 나갔다"

# ── AC-B-017-8: 결과 0건은 성공이 아니다 ───────────────────────────────────

note "AC-B-017-8: 후보 0건 → exit 1 (요약은 그대로 남는다)"
reset_hits
run_engine search --api-index "$IDX/srch.yaml" --sources emptysrc --urls-only rust
assert_code 1 "후보 0건이 성공으로 계상됐다"
assert_line 1 "len(d['search']['candidates'])" "0" "AC-B-017-8 빈 결과 요약이 이상하다"
assert_line 1 "d['search']['sources'][0]['ok']" "True" \
  "AC-B-017-8 소스는 200 이었는데 실패로 기록됐다"

# ── AC-B-017-3: 취득 본문의 링크는 후보가 되지 않는다 ──────────────────────

note "AC-B-017-3: 후보를 실제로 취득 — 본문의 링크는 큐에 들어가지 않는다"
reset_hits
run_engine search --api-index "$IDX/srch.yaml" --sources htmlsrc --max-results 2 rust
assert_code 0 "검색 후 취득이 실패했다"
if [ "$(nlines)" != "3" ]; then
  fail "AC-B-017-8 요약 1줄 + 후보당 1줄이 아니다 (got $(nlines))"
fi
assert_line 2 "d.get('ok')" "True" "후보 문서 취득이 실패했다"
assert_line 3 "d.get('ok')" "True" "후보 문서 취득이 실패했다"
assert_hits "/doc/" "2" "AC-B-017-2 절단 후 후보 수만큼만 두드려야 한다"
assert_hits "/trap/" "0" "AC-B-017-3 취득 본문의 링크가 다시 후보가 됐다 — 재귀 부재가 무너졌다"

note "AC-B-017-3: 구조 — 후보 생성 모듈은 취득·추출 계층을 임포트하지 않는다"
_AST="$("$PY" - "$ROOT" <<'PY'
import ast, pathlib, sys

path = pathlib.Path(sys.argv[1]) / "skills" / "open-reach" / "open_reach" / "search.py"
tree = ast.parse(path.read_text(encoding="utf-8"))
banned = {"fetcher", "batch", "extract", "alternates"}
found = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        found |= {a.name.rsplit(".", 1)[-1] for a in node.names}
    elif isinstance(node, ast.ImportFrom):
        found |= {a.name for a in node.names}
        if node.module:
            found.add(node.module.rsplit(".", 1)[-1])
    elif isinstance(node, ast.Call):
        func = node.func
        name = getattr(func, "attr", None) or getattr(func, "id", None)
        if name in ("import_module", "__import__") and node.args:
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                found.add(arg.value.rsplit(".", 1)[-1])
hit = banned & found
print("BANNED_IMPORT:" + ",".join(sorted(hit)) if hit else "STRUCTURE_OK")
PY
)"
if [ "$_AST" != "STRUCTURE_OK" ]; then
  fail "AC-B-017-3 구조 방벽이 깨졌다 ($_AST)"
fi

finish
