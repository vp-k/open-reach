#!/usr/bin/env bash
# US-B-001 — 공개 본문 조회
# AC-B-001-1 / -2 / -3 / -4
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_lib.sh"

BODY_MARKER="OPENREACH-BODY-MARKER"
SCRIPT_MARKER="OPENREACH-SCRIPT-MARKER"
NAV_MARKER="OPENREACH-NAV-MARKER"
FOOTER_MARKER="OPENREACH-FOOTER-MARKER"

note "AC-B-001-1: 공개 문서 fetch → exit 0, ok=true, 본문 200자 이상"
run_engine fetch "$BASE/public/article"
assert_code 0 "AC-B-001-1 exit code"
assert_expr "d.get('ok')" "True" "AC-B-001-1 ok=true"
assert_expr "len(d.get('content_markdown') or '') >= 200" "True" "AC-B-001-1 본문 200자 이상"
assert_stdout_has "$BODY_MARKER" "AC-B-001-1 본문 마커 보존"

note "AC-B-001-2: script/style/nav/footer 텍스트 제거"
assert_expr "'$SCRIPT_MARKER' not in (d.get('content_markdown') or '')" "True" "AC-B-001-2 script 텍스트 제거"
assert_expr "'$NAV_MARKER' not in (d.get('content_markdown') or '')" "True" "AC-B-001-2 nav 텍스트 제거"
assert_expr "'$FOOTER_MARKER' not in (d.get('content_markdown') or '')" "True" "AC-B-001-2 footer 텍스트 제거"

note "AC-B-001-3: metadata 4필드"
assert_expr "bool((d.get('metadata') or {}).get('title'))" "True" "AC-B-001-3 title"
assert_expr "bool((d.get('metadata') or {}).get('final_url'))" "True" "AC-B-001-3 final_url"
assert_expr "bool((d.get('metadata') or {}).get('content_type'))" "True" "AC-B-001-3 content_type"
assert_expr "bool((d.get('metadata') or {}).get('fetched_at'))" "True" "AC-B-001-3 fetched_at"

note "AC-B-001-4: 본문이 디스크(관측 로그)에 기록되지 않는다 (NG-12)"
leaked=0
while IFS= read -r f; do
  [ -f "$f" ] || continue
  if grep -qF "$BODY_MARKER" "$f" 2>/dev/null; then
    fail "AC-B-001-4 본문 마커가 로그 파일에 기록됨: $f"
    leaked=1
  fi
done < <(find "$ROOT" "$WORK" -type f -name 'observations*.jsonl' 2>/dev/null)
[ "$leaked" -eq 0 ] && note "관측 로그에 본문 미기록 확인"

note "정상 리디렉션은 추종한다"
run_engine fetch "$BASE/redir/public"
assert_code 0 "리디렉션 추종 exit 0"
assert_expr "d.get('ok')" "True" "리디렉션 추종 ok=true"

finish
