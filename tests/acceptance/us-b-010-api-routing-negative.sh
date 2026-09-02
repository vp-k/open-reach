#!/usr/bin/env bash
# US-B-010 — Phase 0 공개 API 라우팅: 조립 규칙 음성 케이스
# AC-B-010-8 / -9 / -10 / -11 / -12 / -13 / -14
#
# 왜 음성만 모았나.
#   2-hop 은 **상대 서버의 응답이 우리 다음 요청 URL 에 영향을 주는** 첫 경로다.
#   리디렉션이 아니라 우리가 자발적으로 조립하는 URL 이라 hop_guard 가 보지 않는다.
#   "가드가 있다"는 코드를 읽어서 확신할 수 있는 종류가 아니므로, 가드가 **작동하지
#   않으면 실패하는** 케이스로 고정한다. 양성 경로(정상 구제)는 US-B-010 양성 테스트가
#   따로 맡는다.
#
# "요청하지 않았다"는 출력만으로는 요청이 없었는지 있었다가 실패했는지 구분되지
# 않는다. 픽스처 서버가 경로별 요청 수를 직접 세고, 여기서 그 수를 단언한다.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_lib.sh"

IDX="$WORK/idx"
mkdir -p "$IDX"

# BASE = http://127.0.0.1:PORT — 인덱스의 host 는 netloc(호스트:포트)로 대조한다
NETLOC="${BASE#http://}"

# write_index <파일명> — stdin 의 YAML 에서 __BASE__/__NETLOC__ 을 치환해 저장한다.
# 따옴표 heredoc 으로 받으므로 value_pattern 의 역슬래시가 셸에 먹히지 않는다.
write_index() {
  sed -e "s|__BASE__|$BASE|g" -e "s|__NETLOC__|$NETLOC|g" > "$IDX/$1"
}

reset_hits() {
  "$PY" - "$BASE" <<'PY' >/dev/null 2>&1 || true
import sys, urllib.request
urllib.request.urlopen(sys.argv[1] + "/_hits/reset", timeout=10).read()
PY
}

hits() { # hits <path> — 픽스처가 센 해당 경로 요청 수 (접두 일치)
  # 선행 슬래시를 떼고 넘긴다. Git Bash(MSYS)는 `/api/step1` 처럼 생긴 인자를
  # 네이티브 프로그램에 넘길 때 `C:/Program Files/Git/api/step1` 로 **변환한다**.
  # 그러면 접두가 영원히 맞지 않아 이 함수가 항상 0 을 돌려주고, 0 을 기대하는
  # 단언은 전부 무조건 통과한다 — 실패할 수 없는 테스트가 된다. 슬래시는 파이썬
  # 쪽에서 다시 붙인다.
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

# 모든 step1 응답에는 next_url=/api/evil 이 심어져 있다. 응답이 지시한 목적지를
# 따라가면 이 경로에 요청이 남는다 — 어느 케이스에서도 0이어야 한다.
assert_no_evil() { assert_hits "/api/evil" "0" "AC-B-010-12 응답이 지시한 목적지를 따라감 ($1)"; }

# ── 인덱스 정의 ────────────────────────────────────────────────────────────

write_index chain3.yaml <<'YAML'
entries:
  - host: __NETLOC__
    url_pattern: "^/api/origin/(?P<name>[a-z0-9]+)$"
    source: "https://example.invalid/api-docs"
    verified_at: "2026-08-30"
    response_kind: html
    chain:
      - request: "__BASE__/api/step1/ok"
        response_kind: json
        select: "crate.max_stable_version"
        value_pattern: '^[0-9]+\.[0-9]+\.[0-9]+$'
        bind: version
      - request: "__BASE__/api/step1/ok"
        response_kind: json
        select: "crate.max_stable_version"
        value_pattern: '^[0-9]+\.[0-9]+\.[0-9]+$'
        bind: version2
      - request: "__BASE__/api/step2/{version2}"
        response_kind: html
YAML

write_index nopattern.yaml <<'YAML'
entries:
  - host: __NETLOC__
    url_pattern: "^/api/origin/(?P<name>[a-z0-9]+)$"
    source: "https://example.invalid/api-docs"
    verified_at: "2026-08-30"
    response_kind: html
    chain:
      - request: "__BASE__/api/step1/ok"
        response_kind: json
        select: "crate.max_stable_version"
        bind: version
      - request: "__BASE__/api/step2/{version}"
        response_kind: html
YAML

write_index hostbind.yaml <<'YAML'
entries:
  - host: __NETLOC__
    url_pattern: "^/api/origin/(?P<name>[a-z0-9]+)$"
    source: "https://example.invalid/api-docs"
    verified_at: "2026-08-30"
    response_kind: html
    chain:
      - request: "__BASE__/api/step1/ok"
        response_kind: json
        select: "host"
        value_pattern: '^[a-z.]+$'
        bind: apihost
      - request: "http://{apihost}/api/step2/x"
        response_kind: html
YAML

# 변종 인덱스 — step1 만 바꿔 가며 조립 규칙 하나씩을 겨눈다.
# value_pattern 은 변종마다 다르다. 같은 패턴을 돌려쓰면 mismatch 변종의 값
# "latest-and-greatest" 가 느슨한 패턴에 **매치되어** 불일치 케이스가 불일치가 아니게 된다.
#   array    — 패턴은 통과하되 값이 스칼라가 아니어서 막혀야 한다
#   mismatch — 앵커된 엄격한 패턴에 걸려야 한다
#   slashy   — 패턴은 일부러 슬래시를 허용한다. 패턴이 뚫려도 세그먼트 검사가 막아야 한다
#   dotdot   — 패턴은 점을 허용한다. 점은 문자로는 합법이지만 `..` **세그먼트**는 거부다
write_variant() { # write_variant <변종> <value_pattern>
  sed -e "s|__VARIANT__|$1|g" -e "s|__PATTERN__|$2|g" <<'YAML' | write_index "step1-$1.yaml"
entries:
  - host: __NETLOC__
    url_pattern: "^/api/origin/(?P<name>[a-z0-9]+)$"
    source: "https://example.invalid/api-docs"
    verified_at: "2026-08-30"
    response_kind: html
    chain:
      - request: "__BASE__/api/step1/__VARIANT__"
        response_kind: json
        select: "crate.max_stable_version"
        value_pattern: '__PATTERN__'
        bind: version
      - request: "__BASE__/api/step2/{version}"
        response_kind: html
YAML
}

# mismatch 의 역슬래시는 두 번 쓴다. sed 치환부에서 `\.` 는 `.` 로 축약되어
# 나가므로, 인덱스 파일에 `\.` 를 남기려면 `\\.` 로 넘겨야 한다.
write_variant array    '^[0-9A-Za-z._/-]+$'
write_variant mismatch '^[0-9]+\\.[0-9]+\\.[0-9]+$'
write_variant slashy   '^[0-9A-Za-z._/-]+$'
write_variant dotdot   '^[0-9A-Za-z._/-]+$'

write_index ok2hop.yaml <<'YAML'
entries:
  - host: __NETLOC__
    url_pattern: "^/api/origin/(?P<name>[a-z0-9]+)$"
    source: "https://example.invalid/api-docs"
    verified_at: "2026-08-30"
    response_kind: html
    chain:
      # 점이 든 버전 문자열(`1.0.229`)로 2-hop 을 완주시킨다. 개정 전 AC-B-010-11 은
      # 점을 세그먼트 이탈 **문자**로 못박아 이 정상 값을 정의상 불가능하게 만들었고,
      # 그래서 crates.io 같은 항목이 출하 인덱스에 오를 수 없었다. 개정 뒤에는 점이
      # 문자로는 합법이고 경로 탈출은 `.`·`..` 세그먼트와 `/`·`%` 가 막는다
      # (R2 SPEC 개정, 사용자 승인). 이 케이스가 그 개정의 증거다.
      - request: "__BASE__/api/step1/ok"
        response_kind: json
        select: "crate.max_stable_version"
        value_pattern: '^[0-9]+\.[0-9]+\.[0-9]+$'
        bind: version
      - request: "__BASE__/api/step2/{version}"
        response_kind: html
YAML

write_index norobots.yaml <<'YAML'
entries:
  - host: __NETLOC__
    url_pattern: "^/api/origin/(?P<name>[a-z0-9]+)$"
    source: "https://example.invalid/api-docs"
    verified_at: "2026-08-30"
    response_kind: html
    chain:
      - request: "__BASE__/api/step1/norobots"
        response_kind: json
        select: "crate.max_stable_version"
        value_pattern: '^[a-z]+$'
        bind: seg
      - request: "__BASE__/norobots/{seg}"
        response_kind: html
YAML

write_index budget.yaml <<'YAML'
entries:
  - host: __NETLOC__
    url_pattern: "^/api/origin/(?P<name>[a-z0-9]+)$"
    source: "https://example.invalid/api-docs"
    verified_at: "2026-08-30"
    response_kind: json
    content_pointer: "body"
    endpoints:
      - "__BASE__/api/ep1"
      - "__BASE__/api/ep2"
      - "__BASE__/api/ep3"
      - "__BASE__/api/ep4"
YAML

# ── 로드 시점에 거부되어야 하는 것 (네트워크 요청 0건) ──────────────────────

note "AC-B-010-8: chain 3단 → 로드 실패, 요청 없음"
reset_hits
run_engine fetch --api-index "$IDX/chain3.yaml" "$BASE/api/origin/ok"
assert_code 3 "chain 길이 3은 로드 실패(종료 코드 3)"
assert_hits "/api/step1" "0" "AC-B-010-8 로드 실패 전에 요청이 나감"
assert_no_evil "chain3"

note "AC-B-010-10: value_pattern 누락 → 로드 실패, 요청 없음"
reset_hits
run_engine fetch --api-index "$IDX/nopattern.yaml" "$BASE/api/origin/ok"
assert_code 3 "value_pattern 없는 항목은 로드 실패(종료 코드 3)"
assert_hits "/api/step1" "0" "AC-B-010-10 패턴 없이 요청이 나감"

note "AC-B-010-12: 호스트를 응답 값으로 바인딩 → 로드 실패"
reset_hits
run_engine fetch --api-index "$IDX/hostbind.yaml" "$BASE/api/origin/ok"
assert_code 3 "스킴·호스트는 템플릿 고정 — bind 는 로드 실패(종료 코드 3)"
assert_hits "/api/step1" "0" "AC-B-010-12 호스트 바인딩 인덱스로 요청이 나감"

# ── AC-B-010-15: 인덱스 자체의 상한과 출처 의무 ─────────────────────────────
#
# 이 두 가지는 NG-9 의 유일한 예외를 성립시키는 조건이다. 지문표에 호스트 리터럴을
# 금지해 놓고 API 인덱스에만 허용한 근거가 "20개 상한 + 출처·확인일 의무"인데,
# 그 조건이 강제되지 않으면 인덱스는 그냥 무제한 호스트 목록이 된다.

{
  echo "entries:"
  for i in $(seq 1 21); do
    printf '  - host: "h%s.invalid"\n' "$i"
    printf '    url_pattern: "^/a%s/(?P<name>[a-z]+)$"\n' "$i"
    printf '    source: "https://example.invalid/api-docs"\n'
    printf '    verified_at: "2026-08-30"\n'
    printf '    response_kind: html\n'
    printf '    endpoints:\n'
    printf '      - "__BASE__/api/step2/{name}"\n'
  done
} | write_index oversize.yaml

write_index noprov.yaml <<'YAML'
entries:
  - host: __NETLOC__
    url_pattern: "^/api/origin/(?P<name>[a-z]+)$"
    source: "https://example.invalid/api-docs"
    response_kind: html
    endpoints:
      - "__BASE__/api/step2/{name}"
YAML

# source 필드가 아예 없다 — "검증 가능한 출처"의 존재 의무를 어긴다 (R2-R8-M2-acc).
write_index nosource.yaml <<'YAML'
entries:
  - host: __NETLOC__
    url_pattern: "^/api/origin/(?P<name>[a-z]+)$"
    verified_at: "2026-08-30"
    response_kind: html
    endpoints:
      - "__BASE__/api/step2/{name}"
YAML

# source 가 http:// — 중간자가 바꿔 쓸 수 있어 검증 가능한 주장이 못 된다. https 만 받는다
# (R2-R8-M2-acc).
write_index httpsource.yaml <<'YAML'
entries:
  - host: __NETLOC__
    url_pattern: "^/api/origin/(?P<name>[a-z]+)$"
    source: "http://example.invalid/api-docs"
    verified_at: "2026-08-30"
    response_kind: html
    endpoints:
      - "__BASE__/api/step2/{name}"
YAML

# source 포트가 범위(0..65535)를 벗어났다 — 열 수 없는 주소는 출처가 되지 못한다
# (R2-R10-M1). 스킴·호스트 검사는 통과하지만 포트 검사가 로드 시점에 막아야 한다.
write_index badportsource.yaml <<'YAML'
entries:
  - host: __NETLOC__
    url_pattern: "^/api/origin/(?P<name>[a-z]+)$"
    source: "https://example.invalid:99999/api-docs"
    verified_at: "2026-08-30"
    response_kind: html
    endpoints:
      - "__BASE__/api/step2/{name}"
YAML

note "AC-B-010-15: 21항목 인덱스 → 로드 실패, 요청 없음"
reset_hits
run_engine fetch --api-index "$IDX/oversize.yaml" "$BASE/api/origin/ok"
assert_code 3 "20항목 상한 초과는 로드 실패(종료 코드 3)"
assert_hits "/api/step" "0" "AC-B-010-15 상한 초과 인덱스로 요청이 나감"

note "AC-B-010-15: verified_at 누락 → 로드 실패, 요청 없음"
reset_hits
run_engine fetch --api-index "$IDX/noprov.yaml" "$BASE/api/origin/ok"
assert_code 3 "확인일 없는 항목은 로드 실패(종료 코드 3)"
assert_hits "/api/step" "0" "AC-B-010-15 출처 미검증 인덱스로 요청이 나감"

note "AC-B-010-15: source 누락 → 로드 실패, 요청 없음 (R2-R8-M2-acc)"
reset_hits
run_engine fetch --api-index "$IDX/nosource.yaml" "$BASE/api/origin/ok"
assert_code 3 "source 없는 항목은 로드 실패(종료 코드 3)"
assert_hits "/api/step" "0" "R2-R8-M2-acc source 없는 인덱스로 요청이 나감"

note "AC-B-010-15: source 가 http:// → 로드 실패, 요청 없음 (R2-R8-M2-acc)"
reset_hits
run_engine fetch --api-index "$IDX/httpsource.yaml" "$BASE/api/origin/ok"
assert_code 3 "http source 는 로드 실패(종료 코드 3)"
assert_hits "/api/step" "0" "R2-R8-M2-acc http source 인덱스로 요청이 나감"

note "AC-B-010-15: source 포트 범위 밖 → 로드 실패, 요청 없음 (R2-R10-M1)"
reset_hits
run_engine fetch --api-index "$IDX/badportsource.yaml" "$BASE/api/origin/ok"
assert_code 3 "열 수 없는 포트의 source 는 로드 실패(종료 코드 3)"
assert_hits "/api/step" "0" "R2-R10-M1 포트 범위 밖 source 인덱스로 요청이 나감"

# ── 1단은 정상이나 2단으로 넘어가면 안 되는 것 ──────────────────────────────

note "AC-B-010-9: select 가 배열 → 2단 요청 없음"
reset_hits
run_engine fetch --api-index "$IDX/step1-array.yaml" "$BASE/api/origin/ok"
assert_expr "d.get('ok')" "False" "배열 바인딩은 구제 실패여야 한다"
assert_hits "/api/step1" "1" "1단은 1회만 요청"
assert_hits "/api/step2" "0" "AC-B-010-9 스칼라가 아닌데 2단 요청이 나감"
assert_no_evil "array"

note "AC-B-010-10: value_pattern 불일치 → 2단 요청 없음"
reset_hits
run_engine fetch --api-index "$IDX/step1-mismatch.yaml" "$BASE/api/origin/ok"
assert_expr "d.get('ok')" "False" "패턴 불일치는 구제 실패여야 한다"
assert_hits "/api/step2" "0" "AC-B-010-10 패턴 불일치인데 2단 요청이 나감"
assert_no_evil "mismatch"

note "AC-B-010-11: 값에 경로 구분자 → 세그먼트 이탈 거부, 2단 요청 없음"
# 이 인덱스의 value_pattern 은 일부러 슬래시를 허용한다. 패턴이 느슨해도
# 세그먼트 검사가 독립적으로 막아야 한다 (이중 검사).
reset_hits
run_engine fetch --api-index "$IDX/step1-slashy.yaml" "$BASE/api/origin/ok"
assert_expr "d.get('ok')" "False" "세그먼트 이탈 값은 구제 실패여야 한다"
assert_hits "/api/step2" "0" "AC-B-010-11 세그먼트 이탈 값으로 2단 요청이 나감"
assert_hits "/norobots" "0" "AC-B-010-11 경로 탈출이 성립했다"
assert_no_evil "slashy"

note "AC-B-010-11: 값이 '..' 세그먼트 → 점을 문자로 허용해도 거부, 2단 요청 없음"
# 개정으로 점은 문자로는 합법이 됐다. 그 완화가 상대 경로 세그먼트까지 열어 주면
# 안 된다 — 여기서 그것을 못 박는다 (R2 SPEC 개정, 사용자 승인).
reset_hits
run_engine fetch --api-index "$IDX/step1-dotdot.yaml" "$BASE/api/origin/ok"
assert_expr "d.get('ok')" "False" "'..' 세그먼트는 구제 실패여야 한다"
assert_hits "/api/step2" "0" "AC-B-010-11 '..' 세그먼트로 2단 요청이 나감"
assert_no_evil "dotdot"

# ── 조립은 성립하나 정책이 막아야 하는 것 ───────────────────────────────────

note "AC-B-010-13: 조립된 URL 이 robots Disallow → policy_blocked"
reset_hits
run_engine fetch --api-index "$IDX/norobots.yaml" "$BASE/api/origin/ok"
assert_code 2 "조립 URL 의 정책 차단은 종료 코드 2"
assert_expr "d.get('failure_reason')" "policy_blocked" "AC-B-010-13 조립 URL robots 재검사"
assert_hits "/norobots" "0" "AC-B-010-13 robots 재검사 없이 요청이 나감"
assert_no_evil "norobots"

# ── 예산 ────────────────────────────────────────────────────────────────────

note "AC-B-010-14: 항목당 요청 예산 3회 — 4번째 엔드포인트는 요청되지 않음"
reset_hits
run_engine fetch --api-index "$IDX/budget.yaml" "$BASE/api/origin/ok"
assert_expr "d.get('ok')" "False" "본문 없는 엔드포인트만으로는 구제 실패"
# R2-R8-M2-acc: ep4=0 만으로는 예산이 3인지 1인지 구분되지 않는다 — 앞 셋이 실제로
# 각각 한 번씩 요청됐고 넷째만 안 됐다는 것을 못 박아야 예산이 **정확히** 3임을 증명한다.
# 예산을 2 로 줄이는 변이는 ep3=0 으로 red 가 된다.
assert_hits "/api/ep1" "1" "R2-R8-M2-acc 예산이 1번째 엔드포인트에 닿지 않음"
assert_hits "/api/ep2" "1" "R2-R8-M2-acc 예산이 2번째 엔드포인트에 닿지 않음"
assert_hits "/api/ep3" "1" "R2-R8-M2-acc 예산이 정확히 3번째 엔드포인트에 닿지 않음"
assert_hits "/api/ep4" "0" "AC-B-010-14 예산 3회를 넘겨 4번째가 요청됨"
assert_no_evil "budget"

# ── SC-9: 성공한 Phase 0 경로의 전수 감사 ──────────────────────────────────
#
# 여기까지는 전부 "막혔는지"를 봤다. 막힌 경로만 검사하면 규칙이 실제로 지켜지는지는
# 알 수 없다 — 아무것도 성공하지 않아도 전부 통과하기 때문이다. SC-9 의 감사 대상은
# **성공한 건**이고, 그래서 성공을 한 번 만들어 놓고 그 성공을 뜯어본다.

note "SC-9: 2-hop 구제 성공 + 성공 경로 전수 감사"
reset_hits
run_engine fetch --api-index "$IDX/ok2hop.yaml" "$BASE/api/origin/ok"
assert_code 0 "2-hop 구제가 성공해야 감사 대상이 생긴다"
assert_expr "d.get('ok')" "True" "2-hop 구제 실패"
assert_expr "d.get('final_route')" "phase0" "구제 성공인데 final_route 가 phase0 이 아니다"

# 임퍼소네이션 0건 — 기계용으로 열어 둔 문을 브라우저인 척 두드리지 않는다 (NG-13)
assert_expr \
  "sum(1 for a in d['attempts'] if a['route'] == 'phase0' and a['impersonate'] is not None)" \
  "0" "SC-9 임퍼소네이션 사용 0건 위반"

# 인덱스에 없는 요청 0건 — phase0 이 두드린 엔드포인트는 전부 인덱스에서 조립된 것이다
assert_expr \
  "sum(1 for a in d['attempts'] if a['route'] == 'phase0' and not str(a.get('endpoint') or '').startswith('$BASE/api/'))" \
  "0" "SC-9 인덱스 밖 엔드포인트 요청"

# 2단이 실제로 돌았다는 것 — 감사가 1단짜리 성공을 2-hop 으로 착각하지 않게
assert_expr "sum(1 for a in d['attempts'] if a['route'] == 'phase0')" "2" \
  "SC-9 감사 대상이 2-hop 이 아니다"

# R2-R7-M1: **치환된 값이 실제 요청 URL 에 실렸는가.** 위 두 단언은 phase0 시도가 2건
# 이라는 개수만 본다 — substitute() 를 통째로 빼도 `/api/step2/{version}` 리터럴을 2번째
# 로 요청하며 개수는 그대로 2이고, step2 는 어떤 경로든 200 을 주므로 ok=True 까지 통과했다.
# step1/ok 의 max_stable_version 은 `1.0.229` 다. 치환이 일어났다면 이 경로가 정확히 한 번
# 요청되고, 일어나지 않았다면 0 이다. 이 단언이 그 맹점을 닫는다.
assert_hits "/api/step2/1.0.229" "1" "R2-R7-M1 치환된 버전이 2단 URL 에 실리지 않았다"

# robots 미검사 0건 — 규칙은 오리진당 한 번만 **가져오고**(캐시) 판정은 URL 마다 다시 한다.
# 그래서 조회 횟수는 1 이다. "판정을 다시 한다"는 쪽은 위 norobots 케이스가 증명한다 —
# 같은 오리진의 캐시된 규칙으로 2단 조립 URL 이 policy_blocked 되었다.
assert_hits "/robots.txt" "1" "SC-9 robots 를 아예 보지 않았다"
assert_no_evil "ok2hop"

finish
