#!/usr/bin/env bash
# US-B-018 — 수확률 기반 거짓 성공 차단 + 밀도 폴백 (R6)
# AC-B-018-1 / -1b / -2 / -3 / -4
#
# 이 라운드에서 **기존 성공을 실패로 뒤집을 수 있는 유일한 변경**이라, 여기서는
# 새로 잡는 것과 건드리지 않기로 한 것을 같은 무게로 고정한다. 판정 경계값
# 자체는 유닛(test_extract_density)이 지키고, 이 파일은 엔진을 끝까지 통과한
# 결과가 같은 결론에 도달하는지 — 즉 배선이 살아 있는지 — 를 본다.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_lib.sh"

IDX="$WORK/idx-b018"
mkdir -p "$IDX"

NETLOC="${BASE#http://}"

write_index() {
  sed -e "s|__BASE__|$BASE|g" -e "s|__NETLOC__|$NETLOC|g" > "$IDX/$1"
}

# 선언된 검색 URL 이라도 수확률 판정은 면제되지 않는다 (AC-B-018-4).
write_index searchidx.yaml <<'YAML'
entries:
  - host: __NETLOC__
    url_pattern: "^/api/origin/(?P<name>[a-z0-9]+)$"
    source: "https://example.invalid/api-docs"
    verified_at: "2026-09-02"
    response_kind: html
    endpoints:
      - "__BASE__/api/step2/{name}"
search:
  - host: __NETLOC__
    url_pattern: '^/starve/page\?q=.+'
    source: "https://example.invalid/search-docs"
    verified_at: "2026-09-02"
YAML

# ── AC-B-018-3: 부피만 크고 수확이 없으면 성공이 아니다 ────────────────────

note "AC-B-018-3: 20만 자를 받고 안내문 한 문단만 건짐 → validation_failed"
run_engine fetch --max-attempts 1 "$BASE/starve/page"
assert_code 1 "수확률 판정이 배선되지 않았다 — 거짓 성공이 통과한다"
assert_expr "d.get('ok')" "False" "AC-B-018-3 안내문이 본문으로 계상됐다"
assert_expr "d.get('failure_reason')" "validation_failed" "AC-B-018-3 판정 사유가 다르다"

note "AC-B-018-4: 선언된 검색 URL 이라도 수확률 면제는 없다 (면제는 nav_shell 하나)"
run_engine fetch --api-index "$IDX/searchidx.yaml" --max-attempts 1 "$BASE/starve/page?q=rust"
assert_code 1 "R5 검색 면제가 수확률 축까지 번졌다"
assert_expr "d.get('failure_reason')" "validation_failed" "AC-B-018-4 검색 예외가 판정을 눌렀다"

# ── AC-B-018-1 / -1b: 밀도 폴백은 본문이 있는 자리를 고른다 ────────────────

note "AC-B-018-1: main/article 선언이 없는 문서 → 본문 컨테이너 채택, 메뉴 배제"
run_engine fetch --max-attempts 1 "$BASE/dense/article"
assert_code 0 "선언 없는 문서에서 본문을 못 골랐다"
assert_expr "d.get('ok')" "True" "AC-B-018-1 밀도 폴백이 동작하지 않았다"
assert_stdout_has "OPENREACH-BODY-MARKER" "AC-B-018-1b 본문이 버려졌다 (깨끗한 조각을 골랐다)"
assert_stdout_lacks "OPENREACH-NAV-MARKER" "AC-B-018-1 메뉴 링크가 본문에 섞였다"

# ── 회귀 방벽: 선언이 있는 문서의 기존 동작은 그대로다 ─────────────────────

note "AC-B-018-2: article 선언이 있는 문서는 발행자 선언이 앞선다 (기존 성공 유지)"
run_engine fetch "$BASE/public/article"
assert_code 0 "AC-B-018-2 기존 성공이 뒤집혔다"
assert_stdout_has "OPENREACH-BODY-MARKER" "AC-B-018-2 선언된 본문이 사라졌다"
assert_stdout_lacks "OPENREACH-NAV-MARKER" "AC-B-018-2 메뉴가 본문에 섞였다"

finish
